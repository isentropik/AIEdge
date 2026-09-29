#pragma once
#include <algorithm>

namespace polar {
// Exactly the two order statistics used by percentile(75) of 360 finite
// samples: rank 269.25. The remaining sample order is not consumed by callers.
// Keep interpolation at the call site to preserve its floating-point order.
inline void selectPercentile75(double* samples) {
    std::nth_element(samples,samples+269,samples+360);
    const auto next=std::min_element(samples+270,samples+360);
    std::iter_swap(samples+270,next);
}
}
