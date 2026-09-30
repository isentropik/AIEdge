#include "RevolutionAccounting.h"
#include <cassert>
#include <iostream>
#include <random>
using namespace meter;
RevolutionObservation frame(double quantity,const RevolutionAssumptions& assumptions,int64_t tick=1000000,const std::string& boot="boot-a") {
    RevolutionObservation out;out.captureUs=tick;out.clockId=boot;
    for(double period:assumptions.periods){double phase=std::fmod(quantity,period);if(phase<0)phase+=period;out.positions.push_back(phase*10/period);}
    return out;
}
void close(double a,double b,double tolerance=1e-7){assert(std::abs(a-b)<=tolerance);}
void ratios_and_rollovers() {
    RevolutionAssumptions assumptions{{10000000,1000000,100000,10000,1000,5},{0,0,0,0,0,0},true,4};
    RevolutionIntervalResolver resolver(assumptions);assert(resolver.configured());
    for(double amount:{.05,5.,100.,1000.,100000.,2.}) {
        const double before=amount==2.?9999999.:255398.98;
        auto result=resolver(frame(before,assumptions),frame(before+amount,assumptions,static_cast<int64_t>((amount+2)*1000000)),Bounds{});
        if(result.status!=Status::Estimated)std::cerr<<"amount="<<amount<<" status="<<int(result.status)<<" reason="<<int(result.reason)<<" min="<<result.minimumFt3<<" max="<<result.maximumFt3<<" phase="<<result.rawPhaseDelta<<" candidates="<<result.candidates<<"\n";
        assert(result.status==Status::Estimated);close(result.estimatedFt3,amount,1e-6);
    }
    auto hidden=resolver(frame(9999999,assumptions),frame(20000000,assumptions,10000003000000LL),Bounds{});
    assert(hidden.status==Status::Ambiguous&&hidden.candidates>1);
    auto step=resolver(frame(255398.98,assumptions),frame(255498.98,assumptions,31000000),Bounds{});
    assert(step.firstTurnOffset==20);close(step.estimatedFt3,100);
    auto full=resolver(frame(255398.98,assumptions),frame(256398.98,assumptions,301000000),Bounds{});
    assert(full.firstTurnOffset==200);close(full.estimatedFt3,1000);
    RevolutionAssumptions water{{64,16,4},{0,0,0},true,1};
    auto generic=RevolutionIntervalResolver(water)(frame(63.8,water),frame(64.1,water,2000000),Bounds{});
    assert(generic.status==Status::Estimated);close(generic.estimatedFt3,.3);
}
void rejection_and_ambiguity() {
    RevolutionAssumptions value{{1000,5},{.1,.1},true,.05};
    RevolutionIntervalResolver resolver(value);auto a=frame(12,value),b=frame(13,value,31000000);
    auto result=resolver(a,b,Bounds{});assert(result.candidates==1&&result.status==Status::Estimated);close(result.estimatedFt3,1);
    b=frame(12,value,301000000);result=resolver(a,b,Bounds{});
    assert(result.status==Status::Ambiguous&&result.candidates>1);
    value.hasMaximumRate=false;result=RevolutionIntervalResolver(value)(a,b,Bounds{});
    assert(result.status==Status::Ambiguous&&std::isinf(result.maximumFt3));
    value.errors={0,0};value.hasMaximumRate=true;value.maximumRate=.1;
    auto backwards=RevolutionIntervalResolver(value)(frame(12,value),frame(11,value,31000000),Bounds{});
    assert(backwards.status==Status::Review&&backwards.reason==Reason::MainRateContradiction);
    b=frame(13,value,31000000,"other-boot");assert(RevolutionIntervalResolver(value)(a,b,Bounds{}).status==Status::Invalid);
    b.clockId=a.clockId;b.captureUs=a.captureUs;assert(RevolutionIntervalResolver(value)(a,b,Bounds{}).status==Status::Invalid);
    b.captureUs=31000000;b.positions[1]=NAN;assert(!RevolutionIntervalResolver(value).accepts(b));
    b=frame(13,value);b.positions[0]=5;assert(!RevolutionIntervalResolver(value).accepts(b));
    for(double bad:{double(NAN),double(INFINITY),-1.,0.}) {auto copy=value;copy.periods[0]=bad;assert(!RevolutionIntervalResolver(copy).configured());}
    auto copy=value;copy.periods={1000,3};assert(!RevolutionIntervalResolver(copy).configured());
    copy=value;copy.errors[0]=.5;assert(!RevolutionIntervalResolver(copy).configured());
    copy=value;copy.maximumRate=INFINITY;assert(!RevolutionIntervalResolver(copy).configured());
    // Work and integer bounds fail closed; never select the first candidate.
    value.periods={5};value.errors={0};value.maximumRate=1e20;
    result=RevolutionIntervalResolver(value)(frame(0,value),frame(1,value,31000000),Bounds{});assert(result.status==Status::Invalid);
}
void fixed_anchor_tracking() {
    RevolutionAssumptions assumptions{{1000,5},{.1,.1},true,.05};
    RevolutionCumulative tracker(assumptions);assert(tracker.reset(frame(0,assumptions)));
    for(int i=1;i<=40;++i){assert(tracker.observe(frame(i,assumptions,1000000+int64_t(i)*30000000)));close(tracker.current().estimatedFt3,i);}
    assert(tracker.observe(frame(40,assumptions,1501000000)));assert(tracker.current().status==Status::Ambiguous);
    const auto through=tracker.current().throughUs;
    assert(!tracker.observe(frame(41,assumptions,1531000000,"new-boot")));assert(!tracker.current().current);
    assert(tracker.current().throughUs==through);
    assert(tracker.reset(frame(41,assumptions,1531000000,"new-boot")));close(tracker.current().minimumFt3,0);
    // Suppress a lower point inside overlapping uncertainty, keeping its
    // accepted range and fixed anchor rather than clamping to the old estimate.
    RevolutionCumulative jitter(assumptions);assert(jitter.reset(frame(0,assumptions)));
    assert(jitter.observe(frame(1,assumptions,31000000)));close(jitter.current().estimatedFt3,1);
    assert(jitter.observe(frame(.99,assumptions,61000000)));
    assert(jitter.current().status==Status::BoundedOnly&&std::isnan(jitter.current().estimatedFt3));
    assert(jitter.observe(frame(1.01,assumptions,91000000)));close(jitter.current().estimatedFt3,1.01);
    assert(jitter.observe(frame(.98,assumptions,121000000)));
    assert(jitter.current().status==Status::BoundedOnly&&std::isnan(jitter.current().estimatedFt3));
    assert(jitter.observe(frame(1.2,assumptions,151000000)));close(jitter.current().estimatedFt3,1.2);
    // Stationary phases near wrap never ratchet positive noise into consumption.
    for(double base:{0.,12.,999.99}) {
        RevolutionCumulative stationary(assumptions);assert(stationary.reset(frame(base,assumptions)));
        for(int i=1;i<=2000;++i){const double noise=(i%3-1)*.04;assert(stationary.observe(frame(base+noise,assumptions,1000000+int64_t(i)*30000000)));
            close(stationary.current().minimumFt3,0);assert(std::isnan(stationary.current().estimatedFt3));}
    }
}
// Independent small-range oracle: enumerate the finest dial's integer turns,
// then intersect each higher dial's possible interval rather than reconstructing
// point readings or using the resolver's highest-to-lowest branch traversal.
std::vector<std::pair<double,double>> oracle(const RevolutionObservation& a,const RevolutionObservation& b,const RevolutionAssumptions& model) {
    std::vector<std::pair<double,double>> out;
    const double upper=model.maximumRate*(b.captureUs-a.captureUs)/1e6;
    const auto last=model.periods.size()-1;const double smallest=model.periods.back();
    const double raw=(b.positions[last]-a.positions[last])*smallest/10,error=2*model.errors[last]*smallest/10;
    for(int k=-2;k<=static_cast<int>(upper/smallest)+3;++k){
        double low=std::max(0.,raw+k*smallest-error),high=std::min(upper,raw+k*smallest+error);if(low>high+1e-9)continue;
        std::vector<std::pair<double,double>> choices{{low,high}};
        for(std::size_t i=0;i<last;++i){std::vector<std::pair<double,double>> next;
            const double p=model.periods[i],d=(b.positions[i]-a.positions[i])*p/10,e=2*model.errors[i]*p/10;
            for(auto range:choices)for(int turn=-2;turn<=static_cast<int>(upper/p)+3;++turn){
                double lo=std::max(range.first,d+turn*p-e),hi=std::min(range.second,d+turn*p+e);if(lo<=hi+1e-9)next.emplace_back(lo,hi);
            }choices=next;
        }out.insert(out.end(),choices.begin(),choices.end());
    }return out;
}
void randomized_oracle() {
    std::mt19937 random(73529);std::uniform_real_distribution<double> base(0,1000),advance(0,80),jitter(-.09,.09);
    RevolutionAssumptions assumptions{{1000,100,5},{.1,.1,.1},true,3};RevolutionIntervalResolver resolver(assumptions);
    for(int n=0;n<1000;++n){const double quantity=base(random);auto a=frame(quantity,assumptions),b=frame(quantity+advance(random),assumptions,31000000);
        for(auto* f:{&a,&b})for(auto& phase:f->positions){phase=std::fmod(phase+jitter(random)+10,10);}
        assert(resolver.accepts(a)&&resolver.accepts(b));auto result=resolver(a,b,Bounds{});auto expected=oracle(a,b,assumptions);
        assert(!expected.empty());assert(result.candidates==static_cast<int64_t>(expected.size()));
        double lo=INFINITY,hi=0;for(auto range:expected){lo=std::min(lo,range.first);hi=std::max(hi,range.second);}close(result.minimumFt3,lo);close(result.maximumFt3,hi);
    }
}
int main(){ratios_and_rollovers();rejection_and_ambiguity();fixed_anchor_tracking();randomized_oracle();std::cout<<"PASS: generic intervals, ratios, wraps, fixed-anchor tracking, ambiguity, bounds and 1000 oracle comparisons (synthetic only)\n";}
