#include "../jomjol_fileserver_ota/RuntimeBundle.h"
#include "sdcard_check.h"
#include <string.h>
#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <unistd.h>
#include <inttypes.h>
#include <sys/stat.h>

#include "esp_rom_crc.h" 
#include "ClassLogFile.h"

static const char *TAG = "SDCARD";

int SDCardCheckRW(void)
{
    LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Basic R/W check started...");
    FILE* pFile = NULL;
    int iCRCMessage = 0;
   
    pFile = fopen("/sdcard/sdcheck.txt","w");
    if (pFile == NULL) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Basic R/W check: (E1) No able to open file to write");
        return -1;
    } 
    else {
        std::string sMessage = "This message is used for a SD-Card basic check!";
        iCRCMessage = esp_rom_crc16_le(0, (uint8_t*)sMessage.c_str(), sMessage.length());
        if (fwrite(sMessage.c_str(), sMessage.length(), 1, pFile) == 0 ) {
            LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Basic R/W check: (E2) Not able to write file");
            fclose(pFile);
            unlink("/sdcard/sdcheck.txt");
            return -2;
        }
        fclose(pFile); 
    }

    pFile = fopen("/sdcard/sdcheck.txt","r");
    if (pFile == NULL) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Basic R/W check: (E3) Not able to open file to read back");
        unlink("/sdcard/sdcheck.txt");
        return -3;
    } 
    else {
        char cReadBuf[50];
        if (fgets(cReadBuf, sizeof(cReadBuf), pFile) == 0) {
            LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Basic R/W check: (E4) Not able to read file back");
            fclose(pFile);
            unlink("/sdcard/sdcheck.txt");
            return -4;
        }
        else {
            if (esp_rom_crc16_le(0, (uint8_t*)cReadBuf, strlen(cReadBuf)) != iCRCMessage) {                 
                LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Basic R/W check: (E5) Read back, but wrong CRC");
                fclose(pFile);
                unlink("/sdcard/sdcheck.txt");
                return -5;
            }
        }      
        fclose(pFile);
    }

    if (unlink("/sdcard/sdcheck.txt") != 0) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Basic R/W check: (E6) Unable to delete the file");
        return -6;
    }

    LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Basic R/W check successful");
    return 0;
}

bool SDCardCheckFolderFilePresence()
{
    struct stat sb;
    bool bRetval = true;

    LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Folder/file presence check started...");
    /* check if folder exists: config */
    if (stat("/sdcard/config", &sb) != 0) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: Folder /config not found");
        bRetval = false;
    }

    /* check if folder exists: html */
    if (stat(MeterBundle::webRoot().c_str(), &sb) != 0) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: Folder /html not found");
        bRetval = false;
    }

    /* check if folder exists: firmware */
    if (stat("/sdcard/firmware", &sb) != 0) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: Folder /firmware not found");
        bRetval = false;
    }

    /* check if folder exists: img_tmp */
    if (stat("/sdcard/img_tmp", &sb) != 0) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: Folder /img_tmp not found");
        bRetval = false;
    }

    /* check if folder exists: log */
    if (stat("/sdcard/log", &sb) != 0) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: Folder /log not found");
        bRetval = false;
    }

    /* check if folder exists: demo */
    if (stat("/sdcard/demo", &sb) != 0) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: Folder /demo not found");
        bRetval = false;
    }

    /* check if file exists: wlan.ini */
    if (stat("/sdcard/wlan.ini", &sb) != 0) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: File /wlan.ini not found");
        bRetval = false;
    }

    /* check if file exists: config.ini */
    if (stat("/sdcard/config/config.ini", &sb) != 0) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: File /config/config.ini not found");
        bRetval = false;
    }

    /* check if file exists: index.html */
    if ((stat(MeterBundle::runtimePath("/sdcard/html/index.html").c_str(), &sb) != 0) && (stat(MeterBundle::runtimePath("/sdcard/html/index.html.gz").c_str(), &sb) != 0)) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: File /html/index.html not found");
        bRetval = false;
    }

    /* check if file exists: ota.html */
    if ((stat(MeterBundle::runtimePath("/sdcard/html/ota_page.html").c_str(), &sb) != 0) && (stat(MeterBundle::runtimePath("/sdcard/html/ota_page.html.gz").c_str(), &sb) != 0)) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: File /html/ota.html not found");
        bRetval = false;
    }

    /* check if file exists: log.html */
    if ((stat(MeterBundle::runtimePath("/sdcard/html/log.html").c_str(), &sb) != 0) && (stat(MeterBundle::runtimePath("/sdcard/html/log.html.gz").c_str(), &sb) != 0)) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: File /html/log.html not found");
        bRetval = false;
    }

    /* check if file exists: common.js */
    if ((stat(MeterBundle::runtimePath("/sdcard/html/common.js").c_str(), &sb) != 0) && (stat(MeterBundle::runtimePath("/sdcard/html/common.js.gz").c_str(), &sb) != 0)) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: File /html/common.js not found");
        bRetval = false;
    }

    /* check if file exists: version.txt */
    if (stat(MeterBundle::runtimePath("/sdcard/html/version.txt").c_str(), &sb) != 0) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Folder/file check: File /html/version.txt not found");
        bRetval = false;
    }

    if (bRetval) {
        LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Folder/file presence check successful");
    }
    
    return bRetval;
}
