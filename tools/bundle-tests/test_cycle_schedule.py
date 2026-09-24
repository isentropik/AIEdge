"""Compare the firmware schedule arithmetic against integer reference cases."""
import sys
import tempfile
if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(3)
import json
import os
from pathlib import Path
import random
import subprocess

ROOT=Path(__file__).resolve().parents[2]
temporary=tempfile.TemporaryDirectory(prefix='aiedge-cycle-schedule-')
OUT=Path(temporary.name)
cpp=OUT/'cycle_schedule_test.cpp'
exe=OUT/'cycle_schedule_test.exe'
source=(ROOT/'code/components/jomjol_flowcontroll/MainFlowControl.cpp').read_text()
begin=source.index('        const int64_t nowUs = esp_timer_get_time();', source.index('void task_autodoFlow'))
end=source.index('\n    }\n\n    while (1)',begin)
block=source[begin:end]
busy_start=source.index('        if (flowisrunning)',source.index('void task_autodoFlow'))
busy_end=source.index('\n        else',busy_start)
busy_block=source[busy_start:busy_end]
cpp.write_text('''#include "CycleSchedule.h"
#include <iostream>
#include <cassert>
#include <string>
using TickType_t=uint32_t;
const int portTICK_PERIOD_MS=10,ESP_LOG_ERROR=1,ESP_LOG_WARN=2;
const char* TAG="test";
int64_t fakeNow=0, scheduledStartUs=0;long auto_interval=30000;
bool autostartIsEnabled=true;TickType_t delayTicks=0;
uint64_t missedSlots=0;bool flowisrunning=false;
int64_t esp_timer_get_time(){return fakeNow;}
void vTaskDelay(TickType_t ticks){delayTicks=ticks;}
struct {void WriteToFile(int,const char*,std::string){}} LogFile;
namespace CycleTelemetry {void schedule(uint64_t missed){missedSlots+=missed;}}
void busyRound(){
'''+busy_block+'''
}
void finish(){while(true){
'''+block+'''
break;}}
int main(){
busyRound();assert(missedSlots==0);
flowisrunning=true;busyRound();assert(missedSlots==1&&flowisrunning);
scheduledStartUs=1000000;fakeNow=2000000;finish();
assert(missedSlots==1&&scheduledStartUs==31000000);
// One blocked current round plus one future slot lost to long housekeeping.
missedSlots=0;scheduledStartUs=1000000;fakeNow=36000000;busyRound();finish();
assert(missedSlots==2&&scheduledStartUs==61000000);
missedSlots=0;
scheduledStartUs=1000000;fakeNow=36000000;finish();
assert(scheduledStartUs==61000000 && delayTicks==2500 && missedSlots==1);
scheduledStartUs=1000000;fakeNow=30999999;finish();
assert(scheduledStartUs==31000000 && delayTicks==1);
scheduledStartUs=1000000;fakeNow=31000000;delayTicks=0;finish();
assert(scheduledStartUs==31000000 && delayTicks==0);
auto_interval=0;finish();assert(!autostartIsEnabled);
int64_t start,now,period;while(std::cin>>start>>now>>period){
auto n=CycleSchedule::after(start,now,period);
std::cout<<n.valid<<" "<<n.atUs<<" "<<n.missed<<"\\n";}}
''')
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(OUT/'zig-global-cache'),ZIG_LOCAL_CACHE_DIR=str(OUT/'zig-local-cache'))
subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG',
               '-I'+str(ROOT/'code/components/jomjol_flowcontroll'),
               str(cpp),'-o',str(exe)],env=env,check=True)
maximum=2**63-1
cases=[(0,t,30_000_000) for t in [0,29_999_999,30_000_000,30_000_001,59_999_999,60_000_000,60_000_001]]
cases += [(0,0,0),(0,0,-1),(-1,0,1),(100,99,1),(maximum,maximum,1),
          (0,maximum,2),(0,maximum,1),(maximum-1,maximum,1)]
rng=random.Random(422)
for _ in range(10000):
    start=rng.randrange(0,maximum)
    now=rng.randrange(start,maximum+1)
    period=rng.randrange(1,maximum+1)
    cases.append((start,now,period))
result=subprocess.run([str(exe)],input=''.join(f'{a} {b} {c}\n' for a,b,c in cases),text=True,capture_output=True,check=True)
lines=result.stdout.splitlines()
assert len(lines)==len(cases)
for case,line in zip(cases,lines):
    start,now,period=case
    valid=start>=0 and now>=start and period>0
    at=start+period
    missed=max(0,(now-at+period-1)//period) if valid else 0
    at+=missed*period
    valid=valid and at<=maximum
    expected=(1,at,missed) if valid else (0,0,0)
    assert tuple(map(int,line.split()))==expected,(case,line,expected)
report={'passed':len(cases),'controller_cases':8,'scope':'real firmware schedule arithmetic and controller delay block; host clock and RTOS stubs',
        'device_cadence_verified':False}
(OUT/'cycle-schedule-results.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))

temporary.cleanup()
