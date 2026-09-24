#include "ClassControllCamera.h"
#include "CameraAccess.h"
#include "RawCaptureObserver.h"
#include "CaptureSettingsSnapshot.h"
#include "StreamPreview.h"
#include "ClassLogFile.h"

#include <stdio.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "esp_log.h"

#include "Helper.h"
#include "statusled.h"
#include "CImageBasis.h"

#include "server_ota.h"
#include "server_GPIO.h"

#include "../../include/defines.h"

#include <esp_event.h>
#include <esp_log.h>
#include <esp_system.h>
#include <nvs_flash.h>
#include <sys/param.h>
#include <string.h>
#include <sys/stat.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_camera.h"

#include "driver/ledc.h"
#include "MainFlowControl.h"

#include "ov2640_sharpness.h"
#include "ov2640_specialEffect.h"
#include "ov2640_contrast_brightness.h"

#if (ESP_IDF_VERSION_MAJOR >= 5)
#include "soc/periph_defs.h"
#include "esp_private/periph_ctrl.h"
#include "soc/gpio_sig_map.h"
#include "soc/gpio_periph.h"
#include "soc/io_mux_reg.h"
#include "esp_rom_gpio.h"
#define gpio_pad_select_gpio esp_rom_gpio_pad_select_gpio
#define gpio_matrix_in(a, b, c) esp_rom_gpio_connect_in_signal(a, b, c)
#define gpio_matrix_out(a, b, c, d) esp_rom_gpio_connect_out_signal(a, b, c, d)
#define ets_delay_us(a) esp_rom_delay_us(a)
#endif

CCamera Camera;
camera_controll_config_temp_t CCstatus;

static const char *TAG = "CAM";

/* Camera live stream */
#define PART_BOUNDARY "123456789000000000000987654321"
static const char *_STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *_STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *_STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

uint8_t *demoImage = NULL;    // Buffer holding the demo image in bytes
#define DEMO_IMAGE_SIZE 30000 // Max size of demo image in bytes

// Camera module bus communications frequency.
// Originally: config.xclk_freq_mhz = 20000000, but this lead to visual artifacts on many modules.
// See https://github.com/espressif/esp32-camera/issues/150#issuecomment-726473652 et al.
#if !defined(XCLK_FREQ_MHZ)
// int xclk = 8;
int xclk = 20; // Orginal value
#else
int xclk = XCLK_FREQ_MHZ;
#endif

static camera_config_t camera_config = {
    .pin_pwdn = CAM_PIN_PWDN,
    .pin_reset = CAM_PIN_RESET,
    .pin_xclk = CAM_PIN_XCLK,
    .pin_sscb_sda = CAM_PIN_SIOD,
    .pin_sscb_scl = CAM_PIN_SIOC,

    .pin_d7 = CAM_PIN_D7,
    .pin_d6 = CAM_PIN_D6,
    .pin_d5 = CAM_PIN_D5,
    .pin_d4 = CAM_PIN_D4,
    .pin_d3 = CAM_PIN_D3,
    .pin_d2 = CAM_PIN_D2,
    .pin_d1 = CAM_PIN_D1,
    .pin_d0 = CAM_PIN_D0,
    .pin_vsync = CAM_PIN_VSYNC,
    .pin_href = CAM_PIN_HREF,
    .pin_pclk = CAM_PIN_PCLK,

    .xclk_freq_hz = (xclk * 1000000),
    .ledc_timer = LEDC_TIMER_0,     // LEDC timer to be used for generating XCLK
    .ledc_channel = LEDC_CHANNEL_0, // LEDC channel to be used for generating XCLK

    .pixel_format = PIXFORMAT_JPEG, // YUV422,GRAYSCALE,RGB565,JPEG
    .frame_size = FRAMESIZE_VGA,    // QQVGA-UXGA Do not use sizes above QVGA when not JPEG
    // .frame_size = FRAMESIZE_UXGA,    //QQVGA-UXGA Do not use sizes above QVGA when not JPEG
    .jpeg_quality = 12,                 // 0-63 lower number means higher quality
    .fb_count = 1,                     // if more than one, i2s runs in continuous mode. Use only with JPEG
    .fb_location = CAMERA_FB_IN_PSRAM, /*!< The location where the frame buffer will be allocated */
    .grab_mode = CAMERA_GRAB_LATEST,   // only from new esp32cam version
};

typedef struct
{
    httpd_req_t *req;
    size_t len;
} jpg_chunking_t;

SemaphoreHandle_t cameraAccessMutex()
{
    static SemaphoreHandle_t mutex = nullptr;
    static portMUX_TYPE creation = portMUX_INITIALIZER_UNLOCKED;
    portENTER_CRITICAL(&creation);
    SemaphoreHandle_t result = mutex;
    portEXIT_CRITICAL(&creation);
    if (result) return result;

    // Allocate outside the spinlock; publish only one instance if callers race.
    SemaphoreHandle_t candidate = xSemaphoreCreateRecursiveMutex();
    if (!candidate) return nullptr;
    portENTER_CRITICAL(&creation);
    if (!mutex) { mutex = candidate; candidate = nullptr; }
    result = mutex;
    portEXIT_CRITICAL(&creation);
    if (candidate) vSemaphoreDelete(candidate);
    return result;
}

CCamera::CCamera(void)
{
#ifdef DEBUG_DETAIL_ON
    ESP_LOGD(TAG, "CreateClassCamera");
#endif
    CCstatus.WaitBeforePicture = 2;

    ledc_init();
}

esp_err_t CCamera::InitCam(void)
{
    ESP_LOGD(TAG, "Init Camera");

    // An unsuccessful retry must never retain the previous ready state.
    CCstatus.CameraInitSuccessful = false;
    CCstatus.CamSensor_id = 0;

    TickType_t cam_xDelay = 100 / portTICK_PERIOD_MS;

    CCstatus.ImageQuality = camera_config.jpeg_quality;
    CCstatus.ImageFrameSize = camera_config.frame_size;

    // De-init in case it was already initialized
    esp_camera_deinit();
    vTaskDelay(cam_xDelay);

    // initialize the camera
    esp_err_t err = esp_camera_init(&camera_config);
    vTaskDelay(cam_xDelay);

    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "Camera Init Failed");
        return err;
    }

    // Get a reference to the sensor
    sensor_t *s = esp_camera_sensor_get();

    if (s != NULL)
    {
        CCstatus.CameraInitSuccessful = true;
        CCstatus.CamSensor_id = s->id.PID;

        // Dump camera module, warn for unsupported modules.
        switch (CCstatus.CamSensor_id)
        {
        case OV2640_PID:
            ESP_LOGI(TAG, "OV2640 camera module detected");
            break;
        case OV3660_PID:
            ESP_LOGI(TAG, "OV3660 camera module detected");
            break;
        case OV5640_PID:
            ESP_LOGI(TAG, "OV5640 camera module detected");
            break;
        default:
            ESP_LOGE(TAG, "Camera module is unknown and not properly supported!");
            CCstatus.CameraInitSuccessful = false;
        }
    }

    if (CCstatus.CameraInitSuccessful)
    {
        return ESP_OK;
    }
    else
    {
        return ESP_FAIL;
    }
}

bool CCamera::testCamera(void)
{
    bool success;
    camera_fb_t *fb = esp_camera_fb_get();

    if (fb)
    {
        success = true;
    }
    else
    {
        success = false;
    }

    esp_camera_fb_return(fb);

    return success;
}

void CCamera::ledc_init(void)
{
#ifdef USE_PWM_LEDFLASH
    // Prepare and then apply the LEDC PWM timer configuration
    ledc_timer_config_t ledc_timer = {};

    ledc_timer.speed_mode = LEDC_MODE;
    ledc_timer.timer_num = LEDC_TIMER;
    ledc_timer.duty_resolution = LEDC_DUTY_RES;
    ledc_timer.freq_hz = LEDC_FREQUENCY; // Set output frequency at 5 kHz
    ledc_timer.clk_cfg = LEDC_AUTO_CLK;

    ESP_ERROR_CHECK(ledc_timer_config(&ledc_timer));

    // Prepare and then apply the LEDC PWM channel configuration
    ledc_channel_config_t ledc_channel = {};

    ledc_channel.speed_mode = LEDC_MODE;
    ledc_channel.channel = LEDC_CHANNEL;
    ledc_channel.timer_sel = LEDC_TIMER;
    ledc_channel.intr_type = LEDC_INTR_DISABLE;
    ledc_channel.gpio_num = LEDC_OUTPUT_IO;
    ledc_channel.duty = 0; // Set duty to 0%
    ledc_channel.hpoint = 0;
    // ledc_channel.flags.output_invert = LEDC_OUTPUT_INVERT;

    ESP_ERROR_CHECK(ledc_channel_config(&ledc_channel));
#endif
}

int CCamera::SetLEDIntensity(int _intrel)
{
    // CCstatus.ImageLedIntensity = (int)(std::min(std::max((float)0, _intrel), (float)100) / 100 * 8191)
    Camera.LedIntensity = (int)((float)(std::min(std::max(0, _intrel), 100)) / 100 * 8191);
    ESP_LOGD(TAG, "Set led_intensity to %i of 8191", Camera.LedIntensity);
    return Camera.LedIntensity;
}

bool CCamera::getCameraInitSuccessful(void)
{
    return CCstatus.CameraInitSuccessful;
}

esp_err_t CCamera::setSensorDatenFromCCstatus(void)
{
    sensor_t *s = esp_camera_sensor_get();

    if (s != NULL)
    {
        s->set_framesize(s, CCstatus.ImageFrameSize);
		
        // s->set_contrast(s, CCstatus.ImageContrast);     // -2 to 2
        // s->set_brightness(s, CCstatus.ImageBrightness); // -2 to 2
        SetCamContrastBrightness(s, CCstatus.ImageContrast, CCstatus.ImageBrightness);
		
        s->set_saturation(s, CCstatus.ImageSaturation); // -2 to 2

        s->set_quality(s, CCstatus.ImageQuality); // 0 - 63
		
        // s->set_gainceiling(s, CCstatus.ImageGainceiling); // Image gain (GAINCEILING_x2, x4, x8, x16, x32, x64 or x128)
        SetCamGainceiling(s, CCstatus.ImageGainceiling);
		
        s->set_gain_ctrl(s, CCstatus.ImageAgc);     // 0 = disable , 1 = enable
        s->set_exposure_ctrl(s, CCstatus.ImageAec); // 0 = disable , 1 = enable
        s->set_hmirror(s, CCstatus.ImageHmirror); // 0 = disable , 1 = enable
        s->set_vflip(s, CCstatus.ImageVflip);     // 0 = disable , 1 = enable
		
        s->set_whitebal(s, CCstatus.ImageAwb);     // 0 = disable , 1 = enable
        s->set_aec2(s, CCstatus.ImageAec2);       // 0 = disable , 1 = enable
        s->set_aec_value(s, CCstatus.ImageAecValue); // 0 to 1200
        // s->set_special_effect(s, CCstatus.ImageSpecialEffect); // 0 to 6 (0 - No Effect, 1 - Negative, 2 - Grayscale, 3 - Red Tint, 4 - Green Tint, 5 - Blue Tint, 6 - Sepia)
        SetCamSpecialEffect(s, CCstatus.ImageSpecialEffect);
        s->set_wb_mode(s, CCstatus.ImageWbMode);               // 0 to 4 - if awb_gain enabled (0 - Auto, 1 - Sunny, 2 - Cloudy, 3 - Office, 4 - Home)
        s->set_ae_level(s, CCstatus.ImageAeLevel);   // -2 to 2
		
        s->set_dcw(s, CCstatus.ImageDcw); // 0 = disable , 1 = enable
        s->set_bpc(s, CCstatus.ImageBpc); // 0 = disable , 1 = enable
        s->set_wpc(s, CCstatus.ImageWpc); // 0 = disable , 1 = enable
        s->set_awb_gain(s, CCstatus.ImageAwbGain); // 0 = disable , 1 = enable
        s->set_agc_gain(s, CCstatus.ImageAgcGain);   // 0 to 30
		
        s->set_raw_gma(s, CCstatus.ImageRawGma); // 0 = disable , 1 = enable
        s->set_lenc(s, CCstatus.ImageLenc);         // 0 = disable , 1 = enable

        // s->set_sharpness(s, CCstatus.ImageSharpness);   // auto-sharpness is not officially supported, default to 0
        SetCamSharpness(CCstatus.ImageAutoSharpness, CCstatus.ImageSharpness);
        s->set_denoise(s, CCstatus.ImageDenoiseLevel); // The OV2640 does not support it, OV3660 and OV5640 (0 to 8)

        TickType_t cam_xDelay = 100 / portTICK_PERIOD_MS;
        vTaskDelay(cam_xDelay);

        return ESP_OK;
    }
    else
    {
        return ESP_FAIL;
    }
}

esp_err_t CCamera::getSensorDatenToCCstatus(void)
{
    sensor_t *s = esp_camera_sensor_get();

    if (s != NULL)
    {
        CCstatus.CamSensor_id = s->id.PID;

        CCstatus.ImageFrameSize = (framesize_t)s->status.framesize;
		
        CCstatus.ImageContrast = s->status.contrast;
        CCstatus.ImageBrightness = s->status.brightness;
        CCstatus.ImageSaturation = s->status.saturation;
		
        CCstatus.ImageQuality = s->status.quality;
		
        CCstatus.ImageGainceiling = (gainceiling_t)s->status.gainceiling;

        CCstatus.ImageAgc = s->status.agc;
        CCstatus.ImageAec = s->status.aec;
        CCstatus.ImageHmirror = s->status.hmirror;
        CCstatus.ImageVflip = s->status.vflip;
		
        CCstatus.ImageAwb = s->status.awb;
        CCstatus.ImageAec2 = s->status.aec2;
        CCstatus.ImageAecValue = s->status.aec_value;
        CCstatus.ImageSpecialEffect = s->status.special_effect;
        CCstatus.ImageWbMode = s->status.wb_mode;
        CCstatus.ImageAeLevel = s->status.ae_level;
		
        CCstatus.ImageDcw = s->status.dcw;
        CCstatus.ImageBpc = s->status.bpc;
        CCstatus.ImageWpc = s->status.wpc;
        CCstatus.ImageAwbGain = s->status.awb_gain;
        CCstatus.ImageAgcGain = s->status.agc_gain;
		
        CCstatus.ImageRawGma = s->status.raw_gma;
        CCstatus.ImageLenc = s->status.lenc;

        // CCstatus.ImageSharpness = s->status.sharpness; // gibt -1 zurÃ¼ck, da es nicht unterstÃ¼tzt wird
        CCstatus.ImageDenoiseLevel = s->status.denoise;

        return ESP_OK;
    }
    else
    {
        return ESP_FAIL;
    }
}

// on the OV5640, gainceiling must be set with the real value (x2>>>gainceilingLevel = 2, .... x128>>>gainceilingLevel = 128)
int CCamera::SetCamGainceiling(sensor_t *s, gainceiling_t gainceilingLevel)
{
	int ret = 0;
		
    if (CCstatus.CamSensor_id == OV2640_PID)
    {
        ret = s->set_gainceiling(s, gainceilingLevel); // Image gain (GAINCEILING_x2, x4, x8, x16, x32, x64 or x128)
    }
    else
    {
        int _level = (1 << ((int)gainceilingLevel + 1));

        ret = s->set_reg(s, 0x3A18, 0xFF, (_level >> 8) & 3) || s->set_reg(s, 0x3A19, 0xFF, _level & 0xFF);

        if (ret == 0)
        {
            // ESP_LOGD(TAG, "Set gainceiling to: %d", gainceilingLevel);
            s->status.gainceiling = gainceilingLevel;
        }
    }

    return ret;
}

void CCamera::SetCamSharpness(bool autoSharpnessEnabled, int sharpnessLevel)
{
    sensor_t *s = esp_camera_sensor_get();

    if (s != NULL)
    {
        if (CCstatus.CamSensor_id == OV2640_PID)
        {
            sharpnessLevel = min(2, max(-2, sharpnessLevel));
            // The OV2640 does not officially support sharpness, so the detour is made with the ov2640_sharpness.cpp.
            if (autoSharpnessEnabled)
            {
                ov2640_enable_auto_sharpness(s);
            }
            else
            {
                ov2640_set_sharpness(s, sharpnessLevel);
            }
        }
        else
        {
            sharpnessLevel = min(3, max(-3, sharpnessLevel));
            // for CAMERA_OV5640 and CAMERA_OV3660
            if (autoSharpnessEnabled)
            {
                // autoSharpness is not supported, default to zero
                s->set_sharpness(s, 0);
            }
            else
            {
                s->set_sharpness(s, sharpnessLevel);
            }
        }
    }
    else
    {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "SetCamSharpness, Failed to get Cam control structure");
    }
}

void CCamera::SetCamSpecialEffect(sensor_t *s, int specialEffect)
{
    if (CCstatus.CamSensor_id == OV2640_PID)
    {
        ov2640_set_special_effect(s, specialEffect);
    }
    else
    {
        s->set_special_effect(s, specialEffect);
    }
}

void CCamera::SetCamContrastBrightness(sensor_t *s, int _contrast, int _brightness)
{
    if (CCstatus.CamSensor_id == OV2640_PID)
    {
        ov2640_set_contrast_brightness(s, _contrast, _brightness);
    }
    else
    {
        s->set_contrast(s, _contrast);     // -2 to 2
        s->set_brightness(s, _brightness); // -2 to 2
    }
}

// - It always zooms to the image center when offsets are zero
// - if imageSize = 0 then the image is not zoomed
// - if imageSize = max value, then the image is fully zoomed in
// - a zoom step is >>> Width + 32 px / Height + 24 px
void CCamera::SanitizeZoomParams(int imageSize, int frameSizeX, int frameSizeY, int &imageWidth, int &imageHeight, int &zoomOffsetX, int &zoomOffsetY)
{
    // for OV2640, This works only if the aspect ratio of 4:3 is preserved in the window size.
    // use only values divisible by 8 without remainder
    imageWidth = CCstatus.ImageWidth + (imageSize * 4 * 8);
    imageHeight = CCstatus.ImageHeight + (imageSize * 3 * 8);

    int _maxX = frameSizeX - imageWidth;
    int _maxY = frameSizeY - imageHeight;

    if ((abs(zoomOffsetX) * 2) > _maxX)
    {
        if (zoomOffsetX > 0)
        {
            zoomOffsetX = _maxX;
        }
        else
        {
            zoomOffsetX = 0;
        }
    }
    else
    {
        if (zoomOffsetX > 0)
        {
            zoomOffsetX = ((_maxX / 2) + zoomOffsetX);
        }
        else
        {
            zoomOffsetX = ((_maxX / 2) + zoomOffsetX);
        }
    }

    if ((abs(zoomOffsetY) * 2) > _maxY)
    {
        if (zoomOffsetY > 0)
        {
            zoomOffsetY = _maxY;
        }
        else
        {
            zoomOffsetY = 0;
        }
    }
    else
    {
        if (zoomOffsetY > 0)
        {
            zoomOffsetY = ((_maxY / 2) + zoomOffsetY);
        }
        else
        {
            zoomOffsetY = ((_maxY / 2) + zoomOffsetY);
        }
    }
}

void CCamera::SetZoomSize(bool zoomEnabled, int zoomOffsetX, int zoomOffsetY, int imageSize, int imageVflip)
{
    sensor_t *s = esp_camera_sensor_get();

    if (s != NULL)
    {
        if (zoomEnabled)
        {
            int _imageSize_temp = 0;
            int _imageWidth = CCstatus.ImageWidth;
            int _imageHeight = CCstatus.ImageHeight;
            int _offsetx = zoomOffsetX;
            int _offsety = zoomOffsetY;
            int frameSizeX;
            int frameSizeY;

            switch (CCstatus.CamSensor_id)
            {
            case OV5640_PID:
                frameSizeX = 2592;
                frameSizeY = 1944;
                // max imageSize = ((frameSizeX - CCstatus.ImageWidth) / 8 / 4) - 1
                // 59 = ((2560 - 640) / 8 / 4) - 1
                if (imageSize < 59)
                {
                    _imageSize_temp = (59 - imageSize);
                }
                SanitizeZoomParams(_imageSize_temp, frameSizeX, frameSizeY, _imageWidth, _imageHeight, _offsetx, _offsety);
                SetCamWindow(s, frameSizeX, frameSizeY, _offsetx, _offsety, _imageWidth, _imageHeight, CCstatus.ImageWidth, CCstatus.ImageHeight, imageVflip);
                break;

            case OV3660_PID:
                frameSizeX = 2048;
                frameSizeY = 1536;
                // max imageSize = ((frameSizeX - CCstatus.ImageWidth) / 8 / 4) -1
                // 43 = ((2048 - 640) / 8 / 4) - 1
                if (imageSize < 43)
                {
                    _imageSize_temp = (43 - imageSize);
                }
                SanitizeZoomParams(_imageSize_temp, frameSizeX, frameSizeY, _imageWidth, _imageHeight, _offsetx, _offsety);
                SetCamWindow(s, frameSizeX, frameSizeY, _offsetx, _offsety, _imageWidth, _imageHeight, CCstatus.ImageWidth, CCstatus.ImageHeight, imageVflip);
                break;

            case OV2640_PID:
                frameSizeX = 1600;
                frameSizeY = 1200;
                // max imageSize = ((frameSizeX - CCstatus.ImageWidth) / 8 / 4) -1
                // 29 = ((1600 - 640) / 8 / 4) - 1
                if (imageSize < 29)
                {
                    _imageSize_temp = (29 - imageSize);
                }
                SanitizeZoomParams(_imageSize_temp, frameSizeX, frameSizeY, _imageWidth, _imageHeight, _offsetx, _offsety);
                SetCamWindow(s, frameSizeX, frameSizeY, _offsetx, _offsety, _imageWidth, _imageHeight, CCstatus.ImageWidth, CCstatus.ImageHeight, imageVflip);
                break;

            default:
                // do nothing
                break;
            }
        }
        else
        {
            s->set_framesize(s, CCstatus.ImageFrameSize);
        }
    }
}

void CCamera::SetQualityZoomSize(int qual, framesize_t resol, bool zoomEnabled, int zoomOffsetX, int zoomOffsetY, int imageSize, int imageVflip)
{
    sensor_t *s = esp_camera_sensor_get();

    // OV2640 has no lower limit on jpeg quality
    if (CCstatus.CamSensor_id == OV5640_PID)
    {
        qual = min(63, max(8, qual));
    }

    SetImageWidthHeightFromResolution(resol);

    if (s != NULL)
    {
        s->set_quality(s, qual);
        SetZoomSize(zoomEnabled, zoomOffsetX, zoomOffsetY, imageSize, imageVflip);
    }
    else
    {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "SetQualityZoomSize, Failed to get Cam control structure");
    }
}

void CCamera::SetCamWindow(sensor_t *s, int frameSizeX, int frameSizeY, int xOffset, int yOffset, int xTotal, int yTotal, int xOutput, int yOutput, int imageVflip)
{
    if (CCstatus.CamSensor_id == OV2640_PID)
    {
        s->set_res_raw(s, 0, 0, 0, 0, xOffset, yOffset, xTotal, yTotal, xOutput, yOutput, false, false);
    }
    else
    {
        // for CAMERA_OV5640 and CAMERA_OV3660
        bool scale = !(xOutput == xTotal && yOutput == yTotal);
        bool binning = (xTotal >= (frameSizeX >> 1));

        if (imageVflip == true)
        {
            s->set_res_raw(s, xOffset, yOffset, xOffset + xTotal - 1, yOffset + yTotal - 1, 0, 0, frameSizeX, frameSizeY, xOutput, yOutput, scale, binning);
        }
        else
        {
            s->set_res_raw(s, xOffset, yOffset, xOffset + xTotal, yOffset + yTotal, 0, 0, frameSizeX, frameSizeY, xOutput, yOutput, scale, binning);
        }
    }
}

static size_t jpg_encode_stream(void *arg, size_t index, const void *data, size_t len)
{
    jpg_chunking_t *j = (jpg_chunking_t *)arg;

    if (!index)
    {
        j->len = 0;
    }

    if (httpd_resp_send_chunk(j->req, (const char *)data, len) != ESP_OK)
    {
        return 0;
    }

    j->len += len;

    return len;
}

static std::string captureSettingsForArchive(int delay)
{
    const auto* sensor=esp_camera_sensor_get();
    if(!sensor)return "";
    auto* gpio=gpio_handler_get();
    std::string lighting;
    if(gpio && gpio->isEnabled())lighting=gpio->captureLightingDescriptor();
    else {
#ifdef USE_PWM_LEDFLASH
        lighting="light-path=builtin-pwm\n";
#else
        lighting="light-path=builtin-digital\n";
#endif
    }
    lighting+="pixel-format="+std::to_string(sensor->pixformat)+"\nxclk-hz="+std::to_string(sensor->xclk_freq_hz)+"\n";
    return CaptureSettingsSnapshot::encode(sensor->status,CCstatus,Camera.LedIntensity,delay,lighting);
}

esp_err_t CCamera::CaptureToBasisImage(CImageBasis *_Image, int delay)
{
    CameraAccess access;
    if (!access) return ESP_ERR_TIMEOUT;
    if (!_Image) return ESP_FAIL;
    _Image->captureTimestampValid = false;
    _Image->captureMonotonicUs = 0;
    const int64_t requiredBytes = int64_t(CCstatus.ImageWidth) * CCstatus.ImageHeight * 3;
    if (!_Image->rgb_image || CCstatus.ImageWidth <= 0 || CCstatus.ImageHeight <= 0 ||
        requiredBytes > _Image->getBufferSize() || _Image->channels != 3 ||
        _Image->width != CCstatus.ImageWidth || _Image->height != CCstatus.ImageHeight)
        return ESP_FAIL;
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("CaptureToBasisImage - Start");
#endif

    _Image->EmptyImage(); // Delete previous stored raw image -> black image

    LEDOnOff(true); // Status-LED on

    if (delay > 0)
    {
        if (!LightOnOff(true)) {
            LightOnOff(false); // Best effort; physical off is not guaranteed after a driver fault.
            LEDOnOff(false);
            LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "CaptureToBasisImage: illumination failed; cycle rejected");
            return ESP_FAIL;
        }
        const TickType_t xDelay = delay / portTICK_PERIOD_MS;
        vTaskDelay(xDelay);
    }

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("CaptureToBasisImage - After LightOn");
#endif

    const std::string archiveSettings=RawCaptureObserver::enabled() ? captureSettingsForArchive(delay) : "";
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb) esp_camera_fb_return(fb);
    fb = esp_camera_fb_get();

    if (!fb)
    {
        LEDOnOff(false);   // Status-LED off
        LightOnOff(false); // Flash-LED off

        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "CaptureToBasisImage: framebuffer unavailable; cycle rejected");

        return ESP_FAIL;
    }

    const int64_t frameCaptureUs = int64_t(fb->timestamp.tv_sec) * 1000000 + fb->timestamp.tv_usec;
    const bool frameTimeValid = !CCstatus.DemoMode && fb->timestamp.tv_sec >= 0 &&
        fb->timestamp.tv_usec >= 0 && fb->timestamp.tv_usec < 1000000 &&
        frameCaptureUs > 0 && frameCaptureUs <= esp_timer_get_time();
    camera_fb_t sourceFrame = *fb;
    if (CCstatus.DemoMode && !loadNextDemoImage(&sourceFrame)) {
        LEDOnOff(false);
        LightOnOff(false);
        esp_camera_fb_return(fb);
        return ESP_FAIL;
    }

    CImageBasis *_zwImage = new CImageBasis("zwImage");

    if (_zwImage)
    {
        _zwImage->LoadFromMemory(sourceFrame.buf, sourceFrame.len);
    }
    else
    {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "CaptureToBasisImage: Can't allocate _zwImage");
    }

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("CaptureToBasisImage - After fb_get");
#endif

    LEDOnOff(false); // Status-LED off

    if (delay > 0 && !LightOnOff(false))
    {
        esp_camera_fb_return(fb);
        delete _zwImage;
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "CaptureToBasisImage: light-off failed; cycle rejected");
        return ESP_FAIL;
    }

    //    TickType_t xDelay = 1000 / portTICK_PERIOD_MS;
    //    vTaskDelay( xDelay );  // wait for power to recover

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("CaptureToBasisImage - After LoadFromMemory");
#endif

    if (_zwImage == NULL || !_zwImage->rgb_image || _zwImage->channels != 3 ||
        _zwImage->width != CCstatus.ImageWidth || _zwImage->height != CCstatus.ImageHeight)
    {
        esp_camera_fb_return(fb);
        delete _zwImage;
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "CaptureToBasisImage: decoded image missing or incompatible");
        return ESP_FAIL;
    }

    if(frameTimeValid)
        RawCaptureObserver::notify(fb->buf,fb->len,frameCaptureUs,CCstatus.ImageWidth,CCstatus.ImageHeight,archiveSettings);
    esp_camera_fb_return(fb);

    // Both allocations hold the validated contiguous RGB frame. Preserve all
    // bytes without the old column-major PSRAM traversal.
    const int64_t copyStarted = esp_timer_get_time();
    memcpy(_Image->rgb_image, _zwImage->rgb_image, static_cast<size_t>(requiredBytes));
    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "capture_rgb_copy_us=" +
        std::to_string(esp_timer_get_time() - copyStarted) +
        " bytes=" + std::to_string(requiredBytes));

    delete _zwImage;

    _Image->captureMonotonicUs = frameCaptureUs;
    _Image->captureTimestampValid = frameTimeValid;

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("CaptureToBasisImage - Done");
#endif

    return ESP_OK;
}

esp_err_t CCamera::CaptureToFile(std::string nm, int delay)
{
    CameraAccess access;
    if (!access) return ESP_ERR_TIMEOUT;
    nm = FormatFileName(nm);
    const string ftype = toUpper(getFileType(nm));
    if (ftype != "BMP" && ftype != "JPG") return ESP_FAIL;
    LEDOnOff(true);
    if (delay > 0) {
        if (!LightOnOff(true)) {
            LightOnOff(false); LEDOnOff(false);
            return ESP_FAIL;
        }
        vTaskDelay(delay / portTICK_PERIOD_MS);
    }
    camera_fb_t* fb = esp_camera_fb_get();
    if (fb) esp_camera_fb_return(fb);
    fb = esp_camera_fb_get();
    LEDOnOff(false);
    const bool offOk = delay <= 0 || LightOnOff(false);
    if (!fb || !offOk) {
        if (fb) esp_camera_fb_return(fb);
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "CaptureToFile: capture or illumination failed");
        return ESP_FAIL;
    }
    uint8_t* buf = nullptr;
    size_t buf_len = 0;
    bool converted = false, valid = false;
    if (ftype == "BMP") {
        converted = true;
        valid = frame2bmp(fb, &buf, &buf_len);
    } else if (fb->format != PIXFORMAT_JPEG) {
        converted = true;
        valid = frame2jpg(fb, CCstatus.ImageQuality, &buf, &buf_len);
    } else {
        buf = fb->buf; buf_len = fb->len; valid = true;
    }
    esp_err_t result = ESP_FAIL;
    if (valid && buf && buf_len) {
        FILE* fp = fopen(nm.c_str(), "wb");
        if (fp) {
            bool written = fwrite(buf, 1, buf_len, fp) == buf_len;
            if (fclose(fp) != 0) written = false;
            if (written) result = ESP_OK;
        }
    }
    if (converted) free(buf);
    esp_camera_fb_return(fb);
    if (result != ESP_OK)
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "CaptureToFile: conversion or file write failed");
    return result;
}

esp_err_t CCamera::CaptureToHTTP(httpd_req_t *req, int delay)
{
    CameraAccess access;
    if (!access) return cameraBusyResponse(req);
    esp_err_t res = ESP_OK;
    size_t fb_len = 0;
    int64_t fr_start = esp_timer_get_time();

    LEDOnOff(true); // Status-LED on

    if (delay > 0)
    {
        if (!LightOnOff(true)) {
            LightOnOff(false); LEDOnOff(false);
            httpd_resp_send_500(req);
            return ESP_FAIL;
        }
        const TickType_t xDelay = delay / portTICK_PERIOD_MS;
        vTaskDelay(xDelay);
    }

    camera_fb_t *fb = esp_camera_fb_get();
    if (fb) esp_camera_fb_return(fb);
    fb = esp_camera_fb_get();

    if (!fb)
    {
        LEDOnOff(false);   // Status-LED off
        LightOnOff(false); // Flash-LED off
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "CaptureToFile: Capture Failed. "
                                                "Check camera module and/or proper electrical connection");
        httpd_resp_send_500(req);
        //        doReboot();

        return ESP_FAIL;
    }

    LEDOnOff(false); // Status-LED off
    if (delay > 0 && !LightOnOff(false)) {
        esp_camera_fb_return(fb);
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }
    if (!fb->buf || !fb->len) {
        esp_camera_fb_return(fb);
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }
    res = httpd_resp_set_type(req, "image/jpeg");

    if (res == ESP_OK)
    {
        res = httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=raw.jpg");
    }

    if (res == ESP_OK)
    {
        if (CCstatus.DemoMode)
        {
            // Use images stored on SD-Card instead of camera image
            LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "Using Demo image!");
            /* Replace Framebuffer with image from SD-Card */
            camera_fb_t sourceFrame = *fb;
            if (!loadNextDemoImage(&sourceFrame) || !sourceFrame.buf || !sourceFrame.len) {
                httpd_resp_send_500(req);
                res = ESP_FAIL;
            } else res = httpd_resp_send(req, (const char *)sourceFrame.buf, sourceFrame.len);
        }
        else
        {
            if (fb->format == PIXFORMAT_JPEG)
            {
                fb_len = fb->len;
                res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
            }
            else
            {
                jpg_chunking_t jchunk = {req, 0};
                res = frame2jpg_cb(fb, 80, jpg_encode_stream, &jchunk) ? ESP_OK : ESP_FAIL;
                if (res == ESP_OK) res = httpd_resp_send_chunk(req, NULL, 0);
                fb_len = jchunk.len;
            }
        }
    }

    esp_camera_fb_return(fb);
    int64_t fr_end = esp_timer_get_time();

    ESP_LOGI(TAG, "JPG: %dKB %dms", (int)(fb_len / 1024), (int)((fr_end - fr_start) / 1000));

    return res;
}

esp_err_t CCamera::CaptureToStream(httpd_req_t *req, bool FlashlightOn)
{
    esp_err_t res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
    if (res == ESP_OK)
        res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));

    while (res == ESP_OK)
    {
        const int64_t frameStart = esp_timer_get_time();
        uint8_t* jpeg = nullptr;
        size_t length = 0;
        {
            // Network transmission must not hold the camera or its framebuffer.
            CameraAccess access(pdMS_TO_TICKS(1000));
            if (!access) return ESP_ERR_TIMEOUT;
            if (CFstatus.changedCameraSettings)
            {
                Camera.setSensorDatenFromCCstatus();
                Camera.SetQualityZoomSize(CCstatus.ImageQuality, CCstatus.ImageFrameSize, CCstatus.ImageZoomEnabled, CCstatus.ImageZoomOffsetX, CCstatus.ImageZoomOffsetY, CCstatus.ImageZoomSize, CCstatus.ImageVflip);
                Camera.LedIntensity = CCstatus.ImageLedIntensity;
                CFstatus.changedCameraSettings = false;
            }
            const int savedIntensity = LedIntensity;
            const int preview = StreamPreview::get();
            const bool previewLight = FlashlightOn || preview >= 0;
            if (preview >= 0) SetLEDIntensity(preview);
            if (previewLight) {
                LEDOnOff(true);
                if (!LightOnOff(true)) {
                    LightOnOff(false);
                    LEDOnOff(false);
                    LedIntensity = savedIntensity;
                    LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Stream illumination failed; ending preview");
                    return ESP_FAIL;
                }
            }
            camera_fb_t* fb = esp_camera_fb_get();
            if (fb) esp_camera_fb_return(fb);
            fb = esp_camera_fb_get();
            // Bound temporary PSRAM use; a single frame, never a queue.
            if (fb && fb->buf && fb->len && fb->len <= 1024 * 1024 && fb->format == PIXFORMAT_JPEG)
            {
                length = fb->len;
                jpeg = static_cast<uint8_t*>(heap_caps_malloc(length, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
                if (jpeg) memcpy(jpeg, fb->buf, length);
            }
            if (fb) esp_camera_fb_return(fb);
            bool lightOffOk = true;
            if (previewLight) { lightOffOk = LightOnOff(false); LEDOnOff(false); }
            LedIntensity = savedIntensity;
            if (!lightOffOk) {
                LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Stream light-off failed; ending preview");
                res = ESP_FAIL;
            }
        }
        if (res != ESP_OK) {
            if (jpeg) heap_caps_free(jpeg);
            return res;
        }
        if (!jpeg)
        {
            LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Stream frame unavailable, invalid or out of memory");
            return ESP_FAIL;
        }
        char header[128];
        int headerLength = snprintf(header, sizeof(header), _STREAM_PART, length);
        if (headerLength < 0 || static_cast<size_t>(headerLength) >= sizeof(header))
            res = ESP_FAIL;
        else
            res = httpd_resp_send_chunk(req, header, headerLength);
        if (res == ESP_OK)
            res = httpd_resp_send_chunk(req, reinterpret_cast<const char*>(jpeg), length);
        if (res == ESP_OK)
            res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
        heap_caps_free(jpeg);
        if (res != ESP_OK) break;
        const int64_t elapsedMs = (esp_timer_get_time() - frameStart) / 1000;
        if (elapsedMs < CAM_LIVESTREAM_REFRESHRATE)
            vTaskDelay(pdMS_TO_TICKS(CAM_LIVESTREAM_REFRESHRATE - elapsedMs) + 1);
    }
    LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Live stream stopped");
    return res;
}

bool CCamera::LightOnOff(bool status)
{
    GpioHandler *gpioHandler = gpio_handler_get();

    if ((gpioHandler != NULL) && (gpioHandler->isEnabled()))
    {
        ESP_LOGD(TAG, "Use gpioHandler to trigger flashlight");
        return gpioHandler->flashLightEnable(status, Camera.LedIntensity);
    }
    else
    {
#ifdef USE_PWM_LEDFLASH
        if (status)
        {
            ESP_LOGD(TAG, "Internal Flash-LED turn on with PWM %d", Camera.LedIntensity);
            if (ledc_set_duty(LEDC_MODE, LEDC_CHANNEL, Camera.LedIntensity) != ESP_OK) return false;
            // Update duty to apply the new value
            return ledc_update_duty(LEDC_MODE, LEDC_CHANNEL) == ESP_OK;
        }
        else
        {
            ESP_LOGD(TAG, "Internal Flash-LED turn off PWM");
            if (ledc_set_duty(LEDC_MODE, LEDC_CHANNEL, 0) != ESP_OK) return false;
            return ledc_update_duty(LEDC_MODE, LEDC_CHANNEL) == ESP_OK;
        }
#else
        // Init the GPIO
        gpio_pad_select_gpio(FLASH_GPIO);

        // Set the GPIO as a push/pull output
        if (gpio_set_direction(FLASH_GPIO, GPIO_MODE_OUTPUT) != ESP_OK) return false;

        if (status)
        {
            return gpio_set_level(FLASH_GPIO, 1) == ESP_OK;
        }
        else
        {
            return gpio_set_level(FLASH_GPIO, 0) == ESP_OK;
        }
#endif
    }
}

void CCamera::LEDOnOff(bool status)
{
    if (xHandle_task_StatusLED == NULL)
    {
        // Init the GPIO
        gpio_pad_select_gpio(BLINK_GPIO);

        /* Set the GPIO as a push/pull output */
        gpio_set_direction(BLINK_GPIO, GPIO_MODE_OUTPUT);

        if (!status)
        {
            gpio_set_level(BLINK_GPIO, 1);
        }
        else
        {
            gpio_set_level(BLINK_GPIO, 0);
        }
    }
}

void CCamera::SetImageWidthHeightFromResolution(framesize_t resol)
{
    if (resol == FRAMESIZE_QVGA)
    {
        CCstatus.ImageWidth = 320;
        CCstatus.ImageHeight = 240;
    }
    else if (resol == FRAMESIZE_VGA)
    {
        CCstatus.ImageWidth = 640;
        CCstatus.ImageHeight = 480;
    }
    else if (resol == FRAMESIZE_SVGA)
    {
        CCstatus.ImageWidth = 800;
        CCstatus.ImageHeight = 600;
    }
    else if (resol == FRAMESIZE_XGA)
    {
        CCstatus.ImageWidth = 1024;
        CCstatus.ImageHeight = 768;
    }
    else if (resol == FRAMESIZE_HD)
    {
        CCstatus.ImageWidth = 1280;
        CCstatus.ImageHeight = 720;
    }
    else if (resol == FRAMESIZE_SXGA)
    {
        CCstatus.ImageWidth = 1280;
        CCstatus.ImageHeight = 1024;
    }
    else if (resol == FRAMESIZE_UXGA)
    {
        CCstatus.ImageWidth = 1600;
        CCstatus.ImageHeight = 1200;
    }
    else if (resol == FRAMESIZE_QXGA)
    {
        CCstatus.ImageWidth = 2048;
        CCstatus.ImageHeight = 1536;
    }
    else if (resol == FRAMESIZE_WQXGA)
    {
        CCstatus.ImageWidth = 2560;
        CCstatus.ImageHeight = 1600;
    }
    else if (resol == FRAMESIZE_QSXGA)
    {
        CCstatus.ImageWidth = 2560;
        CCstatus.ImageHeight = 1920;
    }
    else
    {
        CCstatus.ImageWidth = 640;
        CCstatus.ImageHeight = 480;
    }
}

framesize_t CCamera::TextToFramesize(const char *_size)
{
    if (strcmp(_size, "QVGA") == 0)
    {
        return FRAMESIZE_QVGA; // 320x240
    }
    else if (strcmp(_size, "VGA") == 0)
    {
        return FRAMESIZE_VGA; // 640x480
    }
    else if (strcmp(_size, "SVGA") == 0)
    {
        return FRAMESIZE_SVGA; // 800x600
    }
    else if (strcmp(_size, "XGA") == 0)
    {
        return FRAMESIZE_XGA; // 1024x768
    }
    else if (strcmp(_size, "SXGA") == 0)
    {
        return FRAMESIZE_SXGA; // 1280x1024
    }
    else if (strcmp(_size, "UXGA") == 0)
    {
        return FRAMESIZE_UXGA; // 1600x1200
    }
    else if (strcmp(_size, "QXGA") == 0)
    {
        return FRAMESIZE_QXGA; // 2048x1536
    }
    else if (strcmp(_size, "WQXGA") == 0)
    {
        return FRAMESIZE_WQXGA; // 2560x1600
    }
    else if (strcmp(_size, "QSXGA") == 0)
    {
        return FRAMESIZE_QSXGA; // 2560x1920
    }
    else
    {
        return FRAMESIZE_VGA; // 640x480
    }

    // return CCstatus.ImageFrameSize;
}

std::vector<std::string> demoFiles;

void CCamera::useDemoMode(void)
{
    char line[50];
    demoFiles.clear();

    FILE *fd = fopen("/sdcard/demo/files.txt", "r");

    if (!fd)
    {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Can not start Demo mode, the folder '/sdcard/demo/' does not contain the needed files!");
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "See Details on https://jomjol.github.io/AI-on-the-edge-device-docs/Demo-Mode!");
        return;
    }

    if (!demoImage) demoImage = (uint8_t *)malloc(DEMO_IMAGE_SIZE);

    if (demoImage == NULL)
    {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Unable to acquire required memory for demo image!");
        fclose(fd);
        return;
    }

    while (fgets(line, sizeof(line), fd) != NULL)
    {
        line[strcspn(line, "\r\n")] = '\0';
        if (line[0]) demoFiles.push_back(line);
    }

    fclose(fd);

    LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Using Demo mode (" + std::to_string(demoFiles.size()) + " files) instead of real camera image!");

    for (auto file : demoFiles)
    {
        LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, file);
    }

    CCstatus.DemoMode = true;
}

bool CCamera::loadNextDemoImage(camera_fb_t *fb)
{
    char filename[50];
    int readBytes;
    long fileSize;

    if (!fb || !demoImage || demoFiles.empty()) return false;
    const int length = snprintf(filename, sizeof(filename), "/sdcard/demo/%s", demoFiles[getCountFlowRounds() % demoFiles.size()].c_str());
    if (length < 0 || length >= sizeof(filename)) return false;

    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "Using " + std::string(filename) + " as demo image");

    /* Inject saved image */

    FILE *fp = fopen(filename, "rb");

    if (!fp)
    {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Failed to read file: " + std::string(filename) + "!");
        return false;
    }

    fileSize = GetFileSize(filename);

    if (fileSize <= 0 || fileSize > DEMO_IMAGE_SIZE)
    {
        char buf[100];
        snprintf(buf, sizeof(buf), "Demo Image (%d bytes) is larger than provided buffer (%d bytes)!", (int)fileSize, DEMO_IMAGE_SIZE);
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, std::string(buf));
        fclose(fp);
        return false;
    }

    readBytes = fread(demoImage, 1, DEMO_IMAGE_SIZE, fp);
    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "read " + std::to_string(readBytes) + " bytes");
    const bool readOk = !ferror(fp) && readBytes == fileSize;
    const bool closed = fclose(fp) == 0;
    if (!readOk || !closed) return false;

    fb->buf = demoImage; // Update pointer
    fb->len = readBytes;
    // ToDo do we also need to set height, width, format and timestamp?

    return true;
}

long CCamera::GetFileSize(std::string filename)
{
    struct stat stat_buf;
    long rc = stat(filename.c_str(), &stat_buf);
    return rc == 0 ? stat_buf.st_size : -1;
}
