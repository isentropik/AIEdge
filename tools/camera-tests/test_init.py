"""Compile and exercise actual camera initialization across failed retries."""
from pathlib import Path
import os,subprocess,sys,tempfile
root=Path(__file__).resolve().parents[2]
s=(root/'code/components/jomjol_controlcamera/ClassControllCamera.cpp').read_text(encoding='utf-8')
body=s[s.index('esp_err_t CCamera::InitCam(void)'):s.index('bool CCamera::testCamera')]
harness=r'''
#include <cassert>
#include <cstdio>
#include "CameraInitReport.h"
using esp_err_t=int;using TickType_t=int;
const int ESP_OK=0,ESP_FAIL=-1,ESP_ERR_INVALID_STATE=0x103,portTICK_PERIOD_MS=1;
const int OV2640_PID=0x26,OV3660_PID=0x3660,OV5640_PID=0x5640;
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
struct {bool CameraInitSuccessful=true,CameraInitAttempted=false;int CameraInitError=ESP_ERR_INVALID_STATE;int CamSensor_id=123,ImageQuality=0,ImageFrameSize=0;} CCstatus;
struct {int jpeg_quality=12,frame_size=5;} camera_config;
struct sensor_t {struct {int PID;} id;};
sensor_t sensor{{OV2640_PID}};bool missing=false;int initResult=0,deinits=0,inits=0,queries=0;
void esp_camera_deinit(){assert(!CCstatus.CameraInitSuccessful && CCstatus.CamSensor_id==0);++deinits;}
int esp_camera_init(void*){++inits;return initResult;}
sensor_t* esp_camera_sensor_get(){++queries;return missing?nullptr:&sensor;}
void vTaskDelay(int){}
struct CCamera {esp_err_t InitCam();};
'''+body+r'''
int main(){
 assert(cameraInitReport(false,0x103)=="Not attempted");
 assert(cameraInitReport(true,0)=="Success");
 assert(cameraInitReport(true,0x105)=="Failed (0x105)");
 assert(cameraInitReport(true,-1)=="Failed (0xFFFFFFFF)");
 CCamera c;assert(!CCstatus.CameraInitAttempted && CCstatus.CameraInitError==ESP_ERR_INVALID_STATE);
 for(int id:{OV2640_PID,OV3660_PID,OV5640_PID}){
  sensor.id.PID=id;initResult=0;missing=false;assert(c.InitCam()==ESP_OK);assert(CCstatus.CameraInitAttempted && CCstatus.CameraInitError==ESP_OK);assert(CCstatus.CameraInitSuccessful && CCstatus.CamSensor_id==id);
  initResult=0x105;int before=queries;assert(c.InitCam()==0x105);assert(CCstatus.CameraInitAttempted && CCstatus.CameraInitError==0x105);assert(!CCstatus.CameraInitSuccessful && CCstatus.CamSensor_id==0);assert(queries==before);
 }
 initResult=0;missing=true;CCstatus.CameraInitSuccessful=true;assert(c.InitCam()==ESP_FAIL);assert(CCstatus.CameraInitError==ESP_FAIL);assert(!CCstatus.CameraInitSuccessful && CCstatus.CamSensor_id==0);
 missing=false;sensor.id.PID=999;assert(c.InitCam()==ESP_FAIL);assert(CCstatus.CameraInitError==ESP_FAIL);assert(!CCstatus.CameraInitSuccessful);
 sensor.id.PID=OV2640_PID;assert(c.InitCam()==ESP_OK);assert(CCstatus.CameraInitAttempted && CCstatus.CameraInitError==ESP_OK);assert(CCstatus.CameraInitSuccessful && CCstatus.CamSensor_id==OV2640_PID);
 assert(deinits==9 && inits==9);assert(CCstatus.ImageQuality==12 && CCstatus.ImageFrameSize==5);
 puts("Camera init: supported sensors, failed retry, null/unknown sensor and recovery passed");
}
'''
harness='#include <initializer_list>\n'+harness
if os.name=='nt':
 import ctypes
 ctypes.windll.kernel32.SetErrorMode(3)
with tempfile.TemporaryDirectory(prefix='aiedge-camera-init-') as folder:
 out=Path(folder);source=out/'test.cpp';source.write_text(harness)
 exe=out/('test.exe' if os.name=='nt' else 'test')
 env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(out/'global'),ZIG_LOCAL_CACHE_DIR=str(out/'local'))
 subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG','-I'+str(root/'code/components/jomjol_controlcamera'),str(source),'-o',str(exe)],env=env,check=True)
 subprocess.run([str(exe)],check=True)
