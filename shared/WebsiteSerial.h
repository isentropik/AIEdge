#pragma once
#include "WebsiteHttp.h"
#include "WebsiteSerialParser.h"
#include <new>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "driver/uart_vfs.h"
namespace AIEdgeAuth {
// Serial input never touches credential state from its own task. Jobs are
// serialized with HTTP requests, including password changes and NVS writes.
inline bool queueLocalCommand(httpd_handle_t server,WebsiteHttp& http,const char* command){
    struct Job{WebsiteHttp* http;char command[96];};
    if(!server||!command||std::strlen(command)>=sizeof(Job::command))return false;
    auto* job=new(std::nothrow) Job{};if(!job)return false;
    job->http=&http;std::strcpy(job->command,command);
    const auto result=httpd_queue_work(server,[](void* argument){auto* work=static_cast<Job*>(argument);work->http->localCommand(work->command);wipe(work->command,sizeof work->command);delete work;},job);
    if(result!=ESP_OK){wipe(job->command,sizeof job->command);delete job;return false;}
    return true;
}
inline bool startWebsiteSerial(httpd_handle_t server,WebsiteHttp& http){
    // The loader supplies its existing Improv UART reader instead.
    if(!server||uart_is_driver_installed(UART_NUM_0))return false;
    uart_config_t config={};config.baud_rate=115200;config.data_bits=UART_DATA_8_BITS;config.parity=UART_PARITY_DISABLE;config.stop_bits=UART_STOP_BITS_1;config.flow_ctrl=UART_HW_FLOWCTRL_DISABLE;config.source_clk=UART_SCLK_DEFAULT;
    if(uart_param_config(UART_NUM_0,&config)!=ESP_OK||uart_driver_install(UART_NUM_0,2048,0,0,nullptr,0)!=ESP_OK)return false;
    uart_vfs_dev_use_driver(UART_NUM_0);
    struct Context{httpd_handle_t server;WebsiteHttp* http;};
    auto* context=new(std::nothrow) Context{server,&http};if(!context){uart_vfs_dev_use_nonblocking(UART_NUM_0);uart_driver_delete(UART_NUM_0);return false;}
    const auto result=xTaskCreate([](void* argument){
        auto* c=static_cast<Context*>(argument);SerialParser parser;uint8_t bytes[128];
        for(;;){int n=uart_read_bytes(UART_NUM_0,bytes,sizeof bytes,pdMS_TO_TICKS(100));
            if(n<0){vTaskDelay(pdMS_TO_TICKS(100));continue;}
            for(int i=0;i<n;++i)parser.feed(bytes[i],[&](const char* line){if(!queueLocalCommand(c->server,*c->http,line))std::printf("AIEdge USB password command busy; try again.\n");});
        }
    },"website_usb",4096,context,2,nullptr);
    if(result!=pdPASS){delete context;uart_vfs_dev_use_nonblocking(UART_NUM_0);uart_driver_delete(UART_NUM_0);return false;}
    return true;
}
}
