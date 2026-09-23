#include "../src/DownloadProgress.h"
#include <cassert>
#include <cmath>
#include <iostream>
int main() {
    using AIEdgeDownload::Timeout;
    assert(AIEdgeDownload::timeout(121000,1000)==Timeout::None);
    assert(AIEdgeDownload::timeout(599999,29999)==Timeout::None);
    assert(AIEdgeDownload::timeout(200000,30000)==Timeout::Stalled);
    assert(AIEdgeDownload::timeout(600000,1000)==Timeout::Overall);
    AIEdgeDownload::Progress p;
    assert(AIEdgeDownload::view(p,1000000,9000,true).remainingSeconds<0);
    p.begin(1000);
    assert(AIEdgeDownload::view(p,1000000,2000,true).remainingSeconds<0);
    p.received(200000,5000);
    auto v=AIEdgeDownload::view(p,1000000,5000,true);
    assert(v.percent==20 && v.averageBytesPerSecond==50000 && v.remainingSeconds==16);
    v=AIEdgeDownload::view(p,1000000,15000,true);
    assert(v.waitingForData && v.remainingSeconds<0);
    p.received(400000,16000);
    assert(!AIEdgeDownload::view(p,1000000,16000,true).waitingForData);
    assert(AIEdgeDownload::view(p,1000000,16000,false).remainingSeconds<0);
    p.received(1000000,17000);
    assert(AIEdgeDownload::view(p,1000000,17000,true).percent==100);
    p.begin(20000); // Retry must not carry bytes or a rate from the previous attempt.
    assert(p.bytes==0 && AIEdgeDownload::view(p,1000000,21000,true).remainingSeconds<0);
    p.begin(UINT32_MAX-1999);p.received(300000,2000);
    v=AIEdgeDownload::view(p,1000000,2000,true);
    assert(v.elapsedSeconds==4 && v.averageBytesPerSecond==75000);
    assert(AIEdgeDownload::view(p,0,2000,true).remainingSeconds<0);
    std::cout << "PASS: bytes, rate, ETA, stalls, retry reset, completion and clock wrap\n";
}
