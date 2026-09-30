#include "RevolutionAccounting.h"
#include <memory>
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif
struct AccountingResult {
    int available,current,status,accepted;
    int64_t anchorUs,throughUs;
    double minimum,maximum,estimate;
};
struct AccountingHandle {
    meter::RevolutionIntervalResolver resolver;
    meter::RevolutionCumulative tracker;
    explicit AccountingHandle(const meter::RevolutionAssumptions& value):resolver(value),tracker(value){}
};
void snapshot(const meter::CumulativeResult& value,int accepted,AccountingResult* output) {
    *output={int(value.available),int(value.current),int(value.status),accepted,
        value.anchorUs,value.throughUs,value.minimumFt3,value.maximumFt3,value.estimatedFt3};
}
API int aiedge_accounting_abi(){return 1;}
API void* aiedge_accounting_create(const double* periods,const double* errors,size_t count,int bounded,double maximumRate) {
    if(!periods||!errors||!count||count>16||(bounded!=0&&bounded!=1))return nullptr;
    try {
        meter::RevolutionAssumptions assumptions;
        assumptions.periods.assign(periods,periods+count);assumptions.errors.assign(errors,errors+count);
        assumptions.hasMaximumRate=bounded!=0;assumptions.maximumRate=maximumRate;
        std::unique_ptr<AccountingHandle> handle(new AccountingHandle(assumptions));
        return handle->tracker.configured()?handle.release():nullptr;
    }catch(...){return nullptr;}
}
API void aiedge_accounting_destroy(void* opaque){delete static_cast<AccountingHandle*>(opaque);}
API int aiedge_accounting_observe(void* opaque,const double* positions,size_t count,int64_t tick,const char* clock,size_t clockBytes,AccountingResult* output) {
    if(!opaque||!positions||!count||count>16||!clock||!clockBytes||clockBytes>128||!output)return -1;
    auto* handle=static_cast<AccountingHandle*>(opaque);
    try {
        meter::RevolutionObservation frame;frame.positions.assign(positions,positions+count);
        frame.captureUs=tick;frame.clockId.assign(clock,clockBytes);
        if(!handle->resolver.accepts(frame)){handle->tracker.stale();snapshot(handle->tracker.current(),0,output);return 0;}
        const bool accepted=handle->tracker.current().available?handle->tracker.observe(frame):handle->tracker.reset(frame);
        snapshot(handle->tracker.current(),int(accepted),output);return 0;
    }catch(...){return -2;}
}

API int aiedge_accounting_stale(void* opaque) {
    if(!opaque)return -1;static_cast<AccountingHandle*>(opaque)->tracker.stale();return 0;
}
