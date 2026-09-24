"""Exercise actual history HTTP handlers and display conversion without a device."""
import argparse,sys,tempfile
from pathlib import Path
import os,subprocess,json
ROOT=Path(__file__).resolve().parents[2];C=ROOT/'code/components'
p=argparse.ArgumentParser();p.add_argument('--zig-python',default=sys.executable);args=p.parse_args()
work=tempfile.TemporaryDirectory(prefix='aiedge-history-display-');OUT=Path(work.name)
s=(C/'jomjol_flowcontroll/MainFlowControl.cpp').read_text(encoding='utf-8')
body=s[s.index('static portMUX_TYPE historyMux'):s.index('static portMUX_TYPE polarTestMux')]
p=OUT/'meter_history_http.cpp'
p.write_text(r'''
#include "MeterHistory.h"
#include "MeterStatus.h"
#include "MeterDisplayRuntime.h"
#include "ProcessingAccess.h"
#include "UpdateAccess.h"
#include <cassert>
#include <iostream>
using esp_err_t=int;using portMUX_TYPE=int;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(p) ((void)0)
#define portEXIT_CRITICAL(p) ((void)0)
constexpr int pdPASS=1;bool taskOk=true;int scans=0,deletes=0;void(*worker)(void*)=nullptr;
int64_t esp_timer_get_time(){return 123;}
namespace polar {const char* modelIdentity="model";const char* geometryIdentity="geometry";}
namespace PolarAccounting {meter::SessionResult snapshot(){return {};}}
namespace meter {HistorySummary fixture;
HistorySummary readSegmentHistory(const std::string& dir,const std::string& prefix,const std::string& model,const std::string& calibration,const Bounds&){
 assert(dir=="/sdcard/config"&&prefix=="polar-meter-reference"&&model=="model"&&calibration=="geometry");
 ProcessingAccess p;UpdateAccess u;assert(!p&&!u);++scans;return fixture;
}}
struct httpd_req_t{int content_len=0;bool query=false;std::string code="200 OK",body;};
int httpd_req_get_url_query_len(httpd_req_t* r){return r->query;}
void httpd_resp_set_type(httpd_req_t*,const char*){}
void httpd_resp_set_hdr(httpd_req_t*,const char*,const char*){}
void httpd_resp_set_status(httpd_req_t* r,const char* value){r->code=value;}
int httpd_resp_send(httpd_req_t* r,const char* s,size_t n){r->body.assign(s,n);return 0;}
int httpd_resp_sendstr(httpd_req_t* r,const char* s){r->body=s;return 0;}
int xTaskCreate(void(*f)(void*),const char*,int stack,void*,int,void*){assert(stack==8192);worker=f;return taskOk?pdPASS:0;}
void vTaskDelete(void*){++deletes;}
'''+body+r'''
void show(){httpd_req_t r;handler_meter_history_status(&r);std::cout<<r.body<<"\n";}
void start(){httpd_req_t r;handler_meter_history_refresh(&r);assert(r.code=="202 Accepted"&&historyActive);}
int main(){
 show();httpd_req_t r;r.content_len=1;handler_meter_history_refresh(&r);assert(r.code=="400 Bad Request");
 r={};r.query=true;handler_meter_history_refresh(&r);assert(r.code=="400 Bad Request");
 taskOk=false;r={};handler_meter_history_refresh(&r);assert(r.code=="503 Service Unavailable"&&!historyActive);show();taskOk=true;
 start();show();r={};handler_meter_history_refresh(&r);assert(r.code=="409 Conflict");
 {ProcessingAccess p;worker(nullptr);}assert(scans==0&&!historyActive);show();
 start();{UpdateAccess u;worker(nullptr);}assert(scans==0);show();
 meter::fixture.valid=true;meter::fixture.reason="covered_segments_only";meter::fixture.segments=2;meter::fixture.coveredMinimumFt3=10;meter::fixture.coveredMaximumFt3=12;
 start();worker(nullptr);assert(scans==1);show();
 meter::fixture={};meter::fixture.reason="invalid_record_file";start();worker(nullptr);assert(scans==2&&deletes==4);show();
 historySummary.valid=true;historySummary.coveredMinimumFt3=10;historySummary.coveredMaximumFt3=12;
 meter::displayPreference().store(int(meter::RegisterUnit::CubicFoot));show();
 meter::displayPreference().store(int(meter::RegisterUnit::CubicMetre));show();
 historySummary.coveredMinimumFt3=13;show();
 historySummary.coveredMinimumFt3=10;historySummary.valid=false;show();
 meter::displayPreference().store(int(meter::RegisterUnit::Unknown));show();
 historySummary.valid=true;historySummary.coveredMinimumFt3=std::numeric_limits<double>::infinity();meter::displayPreference().store(int(meter::RegisterUnit::CubicMetre));show();

}
''')
exe=OUT/'meter_history_http.exe';env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(OUT/'zig-global-cache'),ZIG_LOCAL_CACHE_DIR=str(OUT/'zig-local-cache'))
cmd=[args.zig_python,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG']
for name in ['jomjol_tfliteclass','jomjol_controlcamera','jomjol_flowcontroll','jomjol_fileserver_ota']:cmd+=['-I'+str(C/name)]
subprocess.run(cmd+[str(p),'-o',str(exe)],env=env,check=True)
a=list(map(json.loads,subprocess.check_output([str(exe)],text=True).splitlines()))
assert [x['reason'] for x in a[:7]]==['empty_history','task_creation_failed','scan_pending','processing_busy','storage_busy','covered_segments_only','invalid_record_file']
assert a[2]['active'] and not a[2]['valid']
assert a[5]['covered_minimum_ft3']==10 and a[5]['segments']==2
assert a[6]['covered_minimum_ft3'] is None and not a[6]['valid']
assert all(not x['lifetime_complete'] and not x['verified_accuracy'] for x in a)
assert 'APPLY_BASIC_AUTH_FILTER(handler_meter_history_refresh)' in s and 'APPLY_BASIC_AUTH_FILTER(handler_meter_history_status)' in s
print('Actual history worker/HTTP handlers passed: admission, locks, scheduler failure, stale-result clearing, valid/invalid JSON')

assert a[7]['display']=={'unit':'ft3','canonical_unit':'ft3','minimum':10,'maximum':12}
assert a[8]['covered_minimum_ft3']==10 and a[8]['covered_maximum_ft3']==12
assert abs(a[8]['display']['minimum']-10*.028316846592)<1e-10
assert abs(a[8]['display']['maximum']-12*.028316846592)<1e-10
assert all(a[k]['display']['minimum'] is None and a[k]['display']['maximum'] is None for k in (9,10,12))
assert a[11]['display'] is None
print('History display: ft3/m3 conversion, canonical preservation, reversed/nonfinite bounds, invalid history and inactive profile passed')
