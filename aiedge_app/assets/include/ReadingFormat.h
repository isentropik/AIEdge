#pragma once
#include <cmath>
#include <cstddef>
#include <limits>

namespace meter {
// Entries are explicitly ordered from highest to lowest place. Positions are
// normalized to increasing printed numbers by recognition, before this layer.
struct RegisterPlace {
    unsigned dialId;
    double unitsPerStep;
};
struct ReadingFormat {
    const RegisterPlace* places;
    std::size_t count;
    double multiplier;
};
inline bool validReadingFormat(const ReadingFormat& format) {
    if (!format.places || !format.count || format.count > 16 ||
        !std::isfinite(format.multiplier) || format.multiplier <= 0) return false;
    for (std::size_t i=0;i<format.count;++i) {
        const double step=format.places[i].unitsPerStep;
        if (!std::isfinite(step) || step <= 0) return false;
        for (std::size_t j=0;j<i;++j)
            if (format.places[j].dialId == format.places[i].dialId) return false;
        if(i){
            const double ratio=format.places[i-1].unitsPerStep/step;
            if(!std::isfinite(ratio)||ratio<2||ratio>1000000||std::abs(ratio-std::round(ratio))>1e-9)return false;
        }
    }
    const double period=format.places[0].unitsPerStep*10*format.multiplier;
    return std::isfinite(period) && period > 0;
}
inline bool decimalRegister(const ReadingFormat& format) {
    for(std::size_t i=1;i<format.count;++i)
        if(std::abs(format.places[i-1].unitsPerStep/format.places[i].unitsPerStep-10)>1e-9)return false;
    return true;
}
inline bool reconstructRegister(const ReadingFormat& format,
                                const double* positions, std::size_t count,
                                double& total) {
    if (!validReadingFormat(format) || !positions || count != format.count) return false;
    for (std::size_t i=0;i<count;++i)
        if (!std::isfinite(positions[i]) || positions[i]<0 || positions[i]>=10) return false;
    double reconstructed=positions[count-1]*format.places[count-1].unitsPerStep;
    if(!decimalRegister(format)) {
        for(std::size_t i=count-1;i>0;--i){
            const double lowerPeriod=format.places[i].unitsPerStep*10;
            const double period=format.places[i-1].unitsPerStep*10;
            const double expected=positions[i-1]*format.places[i-1].unitsPerStep;
            reconstructed+=std::round((expected-reconstructed)/lowerPeriod)*lowerPeriod;
            reconstructed=std::fmod(reconstructed,period);if(reconstructed<0)reconstructed+=period;
        }
        const double result=reconstructed*format.multiplier;
        if(!std::isfinite(result))return false;
        total=result;return true;
    }
    double period=format.places[count-1].unitsPerStep*100;
    for (std::size_t i=count-1;i>0;--i,period*=10) {
        const double step=period/10, expected=positions[i-1]*step;
        double best=0, distance=std::numeric_limits<double>::infinity();
        for (int digit=0;digit<10;++digit) {
            const double candidate=digit*step+reconstructed;
            double delta=std::fmod(candidate-expected+period/2,period);
            if (delta<0) delta+=period;
            delta=std::abs(delta-period/2);
            if (delta<distance) {best=candidate;distance=delta;}
        }
        reconstructed=best;
    }
    const double result=reconstructed*format.multiplier;
    if (!std::isfinite(result)) return false;
    total=result;
    return true;
}
}
