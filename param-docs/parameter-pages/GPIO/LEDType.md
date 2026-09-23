# Parameter `LEDType`
Default Value: `WS2812`
Type of the `WS2812x` which is connected to GPIO12 (See `IO12` parameter).

`SK6812` retains the existing three-channel GRB format. Select `SK6812_RGBW`
explicitly for four-channel **GRBW** strips. Verify the installed strip's format
and byte order before use; other RGBW orders are not implemented by this option.
The LED count is the actual number of physical pixels (for example 19), not an
adjusted count to compensate for a mismatched byte format.
