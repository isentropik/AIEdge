"""Pure training feature/target/batch code, no model or image-at-import effects."""
import io
import numpy as np
from PIL import Image, ImageFilter
CCW = {'main_10000k', 'main_100k', 'main_1k'}
BINS = 360
PAD = 12

def project(h,points):
 p=np.asarray(points);flat=p.reshape(-1,2);q=np.column_stack([flat,np.ones(len(flat))])@h.T
 return (q[:,:2]/q[:,2,None]).reshape(p.shape)

def sample(a,points):
 x=np.clip(points[...,0],0,a.shape[1]-1.001);y=np.clip(points[...,1],0,a.shape[0]-1.001);ix=x.astype(int);iy=y.astype(int);fx=x-ix;fy=y-iy
 return a[iy,ix]*(1-fx)*(1-fy)+a[iy,ix+1]*fx*(1-fy)+a[iy+1,ix]*(1-fx)*fy+a[iy+1,ix+1]*fx*fy

def features(source_bytes, calibration):
    im = Image.open(io.BytesIO(source_bytes)).convert('L')
    if list(im.size) != calibration['image_size']:
        raise ValueError('Unexpected image size')
    gray = np.asarray(im.filter(ImageFilter.GaussianBlur(.4)), dtype=float)
    h = np.asarray(calibration['homography'])
    pivot = project(h, np.asarray(calibration['needle_pivot']))
    angles = np.arange(BINS) * 2 * np.pi / BINS
    rays = np.column_stack([np.sin(angles), -np.cos(angles)])
    radii = np.linspace(.32, .94, 20)
    coords = project(np.linalg.inv(h), pivot + rays[:, None, :] * radii[None, :, None])
    polar = sample(gray, coords)
    # A shared radial normalization does not privilege any angle.
    dark = (np.percentile(polar, 75, axis=0) - polar) / 128
    return np.concatenate([dark, polar / 255], axis=1).astype('float32')

def labels(rows):
    y = []
    for row in rows:
        value = (10 - row['label']) % 10 if row['dial'] in CCW else row['label']
        delta = (np.arange(BINS) - value * 36 + 180) % 360 - 180
        distribution = np.exp(-.5 * (delta / 2.0) ** 2)
        y.append(distribution / distribution.sum())
    return np.asarray(y, dtype='float32')

def padded(x):
    return np.concatenate([x[:, -PAD:], x, x[:, :PAD]], axis=1)

def batch(rng, rx, ry, sx, sy, mx, my):
    ri = rng.integers(len(rx), size=12)
    si = rng.integers(len(sx), size=10)
    mi = rng.integers(len(mx), size=10)
    legacy_x = np.concatenate([rx[ri], sx[si]])
    legacy_y = np.concatenate([ry[ri], sy[si]])
    shifts = rng.integers(BINS, size=22)
    legacy_x = np.stack([np.roll(x, shift, axis=0) for x, shift in zip(legacy_x, shifts)])
    legacy_y = np.stack([np.roll(y, shift) for y, shift in zip(legacy_y, shifts)])
    # New main rows already vary foreground independently of fixed background.
    # Do not co-rotate these rows, and do not rescale any target or feature.
    bx = np.concatenate([legacy_x, mx[mi]])
    by = np.concatenate([legacy_y, my[mi]])
    return padded(bx), by, {'real_indices':ri.tolist(), 'secondary_indices':si.tolist(),
        'main_indices':mi.tolist(), 'legacy_shifts':shifts.tolist(), 'main_shifts':[0]*10}


LEARNING_RATE = .0005
SEED = 921360
EPOCHS = 35
STEPS = 20

def build_model(tf):
    inputs=tf.keras.Input((384,40))
    x=inputs
    for filters in [16,16]:x=tf.keras.layers.Conv1D(filters,9,activation='relu',padding='valid')(x)
    x=tf.keras.layers.Conv1D(1,9,padding='valid')(x)
    output=tf.keras.layers.Softmax()(tf.keras.layers.Reshape((360,))(x))
    model=tf.keras.Model(inputs,output)
    if model.count_params()!=8241:raise ValueError('Architecture parameter count changed')
    model.compile(optimizer=tf.keras.optimizers.Adam(LEARNING_RATE),loss='categorical_crossentropy')
    return model
