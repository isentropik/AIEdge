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
void tracked_turns_beyond_anchor_search_limit() {
    RevolutionAssumptions assumptions{{5},{0},true,1};
    const auto anchor=frame(0,assumptions);
    RevolutionCumulative tracker(assumptions);assert(tracker.reset(anchor));
    // Consecutive observations establish each turn without guessing across gaps.
    // The unbounded anchor search used to exhaust its branch budget at 640.
    for(int i=1;i<=700;++i) {
        const int64_t tick=1000000+int64_t(i)*1000000;
        assert(tracker.observe(frame(i,assumptions,tick)));
        const auto& result=tracker.current();
        assert(result.current&&result.status==Status::Estimated);
        assert(result.throughUs==tick);close(result.estimatedFt3,i);
    }
    // Without those observations, the search cap must still fail closed.
    const auto gap=RevolutionIntervalResolver(assumptions)(anchor,frame(640,assumptions,641000000),Bounds{});
    assert(gap.status==Status::Invalid&&gap.reason==Reason::TurnCountUnresolved);
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
void retained_branch_paths() {
    RevolutionAssumptions a;
    a.periods={10000000,1000000,100000,10000,1000,5};
    a.errors=std::vector<double>(6,.1);a.hasMaximumRate=true;a.maximumRate=1700.0/3600;
    for(bool partial:{false,true}) {
        RevolutionCumulative t(a);assert(t.reset(frame(0,a,0)));
        for(int sec=12;sec<=120;sec+=6) {
            auto f=frame(0,a,int64_t(sec)*1000000);
            if(partial) {f.observed={false,false,false,false,false,true};for(size_t i=0;i<5;++i)f.positions[i]=NAN;}
            assert(t.observe(f));auto r=t.current();
            assert(r.status==Status::Ambiguous&&!std::isfinite(r.estimatedFt3));
            assert(r.minimumFt3==0&&r.maximumFt3>=5&&r.maximumFt3<=5.100001);
        }
    }
    RevolutionCumulative resolved(a);auto f=frame(0,a,0);f.positions[4]=.09;
    assert(resolved.reset(f));f.captureUs=12000000;assert(resolved.observe(f));
    assert(resolved.current().status==Status::Ambiguous);
    for(int i=1;i<=200;++i) {
        f=frame(i*.5,a,(12+int64_t(i)*6)*1000000);
        f.positions[4]=std::fmod(f.positions[4]+(i<200?.09:-.09)+10,10);
        assert(resolved.observe(f));
    }
    assert(resolved.current().status==Status::Estimated);close(resolved.current().estimatedFt3,100);
    RevolutionAssumptions single;single.periods={5};single.errors={.1};single.hasMaximumRate=true;single.maximumRate=1;
    RevolutionCumulative limited(single);assert(limited.reset(frame(0,single,0)));
    assert(!limited.observe(frame(0,single,1000000000)));
    assert(limited.current().throughUs==0&&!limited.current().current&&!std::isfinite(limited.current().estimatedFt3));
}

void randomized_retained_paths() {
    RevolutionAssumptions a;a.periods={10000,1000,5};a.errors={.1,.1,.1};a.hasMaximumRate=true;a.maximumRate=1700.0/3600;
    for(int seed=0;seed<30;++seed) {
        std::mt19937 generator(seed);std::uniform_real_distribution<double> unit(0,1);
        double q=200000+unit(generator)*100000,initial=q;int64_t tick=0;RevolutionCumulative t(a);
        for(int i=0;i<120;++i) {
            if(i){int64_t dt=3000000+int64_t(unit(generator)*15000000);q+=unit(generator)*a.maximumRate*double(dt)/1000000;tick+=dt;}
            auto f=frame(q,a,tick);
            for(auto& p:f.positions)p=std::fmod(p+(unit(generator)*2-1)*.099+10,10);
            if(i%3){f.observed={false,false,true};f.positions[0]=f.positions[1]=NAN;}
            assert(i?t.observe(f):t.reset(f));auto r=t.current();
            assert(r.minimumFt3<=q-initial+1e-6&&r.maximumFt3>=q-initial-1e-6);
        }
    }
}

int main(){retained_branch_paths();randomized_retained_paths();ratios_and_rollovers();rejection_and_ambiguity();fixed_anchor_tracking();tracked_turns_beyond_anchor_search_limit();randomized_oracle();std::cout<<"PASS: generic intervals, ratios, wraps, fixed-anchor tracking beyond search limit, ambiguity, bounds and 1000 oracle comparisons (synthetic only)\n";}
