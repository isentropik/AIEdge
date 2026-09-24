"""Actual CaptureToBasisImage body with camera/decode/timing failure fixtures."""
import argparse, tempfile
import json
import os
from pathlib import Path
import subprocess

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--zig-python',help='Python executable with ziglang installed')
parser.add_argument('--cxx',default='c++')
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[2]
temporary=tempfile.TemporaryDirectory(prefix='aiedge-capture-')
OUT=Path(temporary.name)
source=(ROOT/'code/components/jomjol_controlcamera/ClassControllCamera.cpp').read_text(encoding='utf-8')
body=source[source.index('esp_err_t CCamera::CaptureToBasisImage'):source.index('esp_err_t CCamera::CaptureToFile')]
harness=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include "RawCaptureObserver.h"
using std::string;
using stbi_uc=uint8_t;
using esp_err_t=int;
using TickType_t=int;
const int ESP_OK=0,ESP_FAIL=-1,ESP_ERR_TIMEOUT=-2,ESP_LOG_ERROR=1,ESP_LOG_DEBUG=2,portTICK_PERIOD_MS=1;
bool cameraAvailable=true;
struct CameraAccess {explicit operator bool() const {return cameraAvailable;}};
const char* TAG="test";
struct {int ImageWidth=2,ImageHeight=2;bool DemoMode=false;} CCstatus;
struct Logger {void WriteToFile(int,const char*,string){} } LogFile;
bool decodeOk=true,wrongSize=false,led=false,light=false,lightFails=false,offFails=false;
bool demoOk=true;uint8_t demoBytes[2]={4,5};uint8_t* decodedSource=nullptr;
int returns=0,captureGets=0,reboots=0,observed=0;
struct CImageBasis {
 int channels=3,width=CCstatus.ImageWidth,height=CCstatus.ImageHeight,capacity=width*height*3;
 std::vector<uint8_t> data;
 uint8_t* rgb_image;
 int64_t captureMonotonicUs=777;
 bool captureTimestampValid=true;
 CImageBasis(string):data(capacity,88),rgb_image(data.data()){}
 int getBufferSize(){return capacity;}
 void EmptyImage(){std::memset(rgb_image,0,capacity);}
 void LoadFromMemory(uint8_t* bytes,int){decodedSource=bytes;for(size_t i=0;i<data.size();++i)data[i]=uint8_t(i*19+7);if(!decodeOk)rgb_image=nullptr;if(wrongSize)width=3;}
};
struct camera_fb_t {uint8_t* buf=nullptr;int len=1;struct {int64_t tv_sec=2,tv_usec=345;} timestamp;};
uint8_t originalBytes[3]={1,2,3};
camera_fb_t first,second;
camera_fb_t* frames[2]={&first,&second};
camera_fb_t* esp_camera_fb_get(){return frames[captureGets++];}
void esp_camera_fb_return(camera_fb_t* f){assert(f);++returns;}
int64_t esp_timer_get_time(){return 3000000;}
void doReboot(){++reboots;assert(false);}
void vTaskDelay(int){}
std::string captureSettingsForArchive(int delay){assert(delay==10);return "snapshot";}
class CCamera {
public:
 void LEDOnOff(bool state){led=state;}
 bool LightOnOff(bool state){light=state;return !(state?lightFails:offFails);}
 bool loadNextDemoImage(camera_fb_t* f){if(!demoOk)return false;f->buf=demoBytes;f->len=2;return true;}
 esp_err_t CaptureToBasisImage(CImageBasis*,int);
};
'''+body+r'''
int main(){
 CCamera camera;
 assert(RawCaptureObserver::install([](const unsigned char* bytes,size_t length,int64_t time,int width,int height,const std::string& settings){
   assert(settings=="snapshot");
   assert(bytes==originalBytes && length==3 && time==2000345 && width==CCstatus.ImageWidth && height==CCstatus.ImageHeight);
   assert(!led && !light);++observed;
 }));
 assert(!RawCaptureObserver::install(nullptr));
 auto reset=[](){
  demoOk=true;decodedSource=nullptr;decodeOk=true;wrongSize=false;lightFails=offFails=false;CCstatus.DemoMode=false;CCstatus.ImageWidth=CCstatus.ImageHeight=2;
  captureGets=returns=0;led=light=false;frames[0]=&first;frames[1]=&second;
  second.timestamp.tv_sec=2;second.timestamp.tv_usec=345;
  second.buf=originalBytes;second.len=3;observed=0;
 };
 auto failure=[&](CImageBasis& image){
  assert(camera.CaptureToBasisImage(&image,10)==ESP_FAIL);
  assert(!image.captureTimestampValid && image.captureMonotonicUs==0);
  assert(!led && !light && reboots==0);
  assert(observed==0);
 };
 {reset();CImageBasis image("busy");cameraAvailable=false;
  assert(camera.CaptureToBasisImage(&image,10)==ESP_ERR_TIMEOUT);assert(captureGets==0);
  cameraAvailable=true;}
 reset();assert(camera.CaptureToBasisImage(nullptr,10)==ESP_FAIL);assert(captureGets==0);
 {reset();CImageBasis image("light failure");lightFails=true;failure(image);assert(captureGets==0);}
 {reset();CImageBasis image("off failure");offFails=true;failure(image);assert(captureGets==2&&returns==2);}
 {reset();CImageBasis image("test");image.capacity=11;failure(image);assert(captureGets==0);}
 {reset();CImageBasis image("test");image.width=3;failure(image);assert(captureGets==0);}
 {reset();CImageBasis image("test");image.rgb_image=nullptr;failure(image);assert(captureGets==0);}
 {reset();CImageBasis image("test");frames[1]=nullptr;failure(image);assert(returns==1);}
 {reset();CImageBasis image("test");decodeOk=false;failure(image);assert(returns==2);}
 {reset();CImageBasis image("test");wrongSize=true;failure(image);assert(returns==2);}
 {reset();CImageBasis image("test");frames[0]=nullptr;
  assert(camera.CaptureToBasisImage(&image,10)==ESP_OK && returns==1);
  assert(image.captureTimestampValid && image.captureMonotonicUs==2000345);
  assert(observed==1);
  assert(!led && !light);for(size_t i=0;i<image.data.size();++i)assert(image.data[i]==uint8_t(i*19+7));}
 {reset();CImageBasis image("test");CCstatus.DemoMode=true;
  assert(camera.CaptureToBasisImage(&image,10)==ESP_OK);assert(!image.captureTimestampValid);assert(observed==0);assert(decodedSource==demoBytes);assert(second.buf==originalBytes&&second.len==3);}
 {reset();CImageBasis image("missing demo");CCstatus.DemoMode=true;demoOk=false;failure(image);assert(decodedSource==nullptr&&returns==2);assert(second.buf==originalBytes&&second.len==3);}
 {reset();CImageBasis image("test");second.timestamp.tv_sec=4;
  assert(camera.CaptureToBasisImage(&image,10)==ESP_OK);assert(!image.captureTimestampValid);assert(observed==0);}
 {reset();CImageBasis image("test");second.timestamp.tv_usec=-1;
  assert(camera.CaptureToBasisImage(&image,10)==ESP_OK);assert(!image.captureTimestampValid);assert(observed==0);}
 {reset();CCstatus.ImageWidth=640;CCstatus.ImageHeight=480;CImageBasis image("full frame");
  assert(camera.CaptureToBasisImage(&image,10)==ESP_OK);assert(observed==1&&returns==2);
  assert(image.data.size()==921600);
  for(size_t i=0;i<image.data.size();++i)assert(image.data[i]==uint8_t(i*19+7));}
}
'''
cpp=OUT/'capture_test.cpp';exe=OUT/'capture_test.exe';cpp.write_text(harness,encoding='utf-8')
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(OUT/'zig-global-cache'),ZIG_LOCAL_CACHE_DIR=str(OUT/'zig-local-cache'))
subprocess.run(([args.zig_python,'-m','ziglang','c++'] if args.zig_python else [args.cxx])+['-std=c++11','-O2', '-UNDEBUG','-I'+str(ROOT/'code/components/jomjol_controlcamera'),str(cpp),'-o',str(exe)],check=True,env=env)
subprocess.run([str(exe)],check=True)
report={'passed':16,'scope':'actual capture body; full 640x480 byte comparison; illumination activation/off rejection; camera, decode and clock stubs',
        'hardware_capture_verified':False}
(OUT/'capture-results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));temporary.cleanup()

