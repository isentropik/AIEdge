# Parameter `LEDColor`
Values: `R G B [W]`, each an integer from `0` (off) to `255` (full).

The optional fourth value controls the dedicated white channel for
`LEDType = SK6812_RGBW`. Older three-value settings use W=0. Nonzero W is rejected
for RGB strip types, because those strips have no fourth channel.

White-only example: `LEDColor = 0 0 0 255`.

Camera LED intensity scales these underlying channel values together for camera
capture and light-enabled preview/stream startup. Intensity zero sends all channels
off. Scaling is rounded to the nearest 8-bit channel value; tiny color/intensity
combinations can therefore round to zero. The configured color is not overwritten
when intensity changes.
