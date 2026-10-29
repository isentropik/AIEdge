"""Array-only uncertain procedural-foreground method; no data or file I/O.

Inputs must already pass source-family exclusion and provenance checks. This
module does not certify annotations or reconstruct hidden physical background.
"""
import hashlib
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
SEEDS = (921360, 921361, 921362)
TARGETS = tuple(f'{i // 10}.{i % 10}' for i in range(100))

def sha(data):
    return hashlib.sha256(data).hexdigest()

def polygon_mask(size, polygons):
    if len(size) != 2 or min(size) <= 0:
        raise ValueError('Invalid image size')
    im = Image.new('L', tuple(size), 0)
    draw = ImageDraw.Draw(im)
    for poly in polygons:
        points = np.asarray(poly, dtype=float)
        if points.shape[0] < 3 or points.shape[1:] != (2,) or not np.isfinite(points).all():
            raise ValueError('Invalid polygon')
        draw.polygon([tuple(p) for p in points], fill=255)
    return np.asarray(im) != 0

def effective_core(annotation):
    size = annotation['image_size']
    core = polygon_mask(size, annotation['opaque_foreground_core_polygons'])
    uncertain = polygon_mask(size, annotation['uncertain_contact_regions'])
    usable = core & ~uncertain
    if not np.any(usable):
        raise ValueError('No conservative foreground samples')
    return usable, uncertain

def foreground_color(rgb, annotation):
    """Exact integer centers only; no filtered/interpolated source samples."""
    usable, _ = effective_core(annotation)
    if rgb.dtype != np.uint8 or rgb.shape != (*usable.shape, 3):
        raise ValueError('Unexpected source RGB shape/type')
    return np.median(rgb[usable].astype(np.float64), axis=0)

def project(h, points):
    a = np.asarray(points, dtype=np.float64)
    flat = a.reshape(-1, 2)
    z = np.column_stack((flat, np.ones(len(flat)))) @ np.asarray(h, dtype=np.float64).T
    if not np.isfinite(z).all() or np.any(np.abs(z[:, 2]) < 1e-10):
        raise ValueError('Nonfinite/singular projective geometry')
    return (z[:, :2] / z[:, 2:3]).reshape(a.shape)

def validated_geometry(cal, annotation):
    h = np.asarray(cal['homography'], dtype=np.float64)
    if h.shape != (3, 3) or not np.isfinite(h).all() or abs(np.linalg.det(h)) < 1e-12:
        raise ValueError('Invalid homography')
    if cal['direction'] != 'ccw' or cal['image_size'] != annotation['image_size']:
        raise ValueError('Wrong printed convention or size')
    if cal['needle_pivot'] != annotation['geometry_seed']['pivot']:
        raise ValueError('Pivot changed')
    p = project(h, cal['needle_pivot'])
    if np.linalg.norm(p) >= 1:
        raise ValueError('Pivot must be inside declared rim')
    tip = project(h, annotation['geometry_seed']['visible_tip'])
    v = tip - p
    if np.linalg.norm(v) < 1e-8:
        raise ValueError('Degenerate source shaft')
    return h, p, v / np.linalg.norm(v)

def moved_polygon(cal, annotation, target):
    value = float(target)
    if not math.isfinite(value) or not 0 <= value < 10:
        raise ValueError('Target must be a finite printed value in [0,10)')
    h, p, initial = validated_geometry(cal, annotation)
    clockwise = (-value) % 10
    theta = clockwise * (2 * math.pi / 10)
    q = np.array([math.sin(theta), -math.cos(theta)])
    wanted = (q - p) / np.linalg.norm(q - p)
    dot = float(initial @ wanted)
    cross = float(initial[0] * wanted[1] - initial[1] * wanted[0])
    rotation = np.array([[dot, -cross], [cross, dot]])
    poly = project(h, annotation['candidate_procedural_silhouette'])
    transformed = p + (poly - p) @ rotation.T
    return project(np.linalg.inv(h), transformed), {'pivot_canonical': p.tolist(),
        'target_rim_canonical': q.tolist(), 'target_ray': wanted.tolist(),
        'conditional_label': str(target), 'printed_direction': 'ccw'}

def make_background(rgb, annotation, seed):
    """Impute a conservative fixed removal area; not recovered hidden truth."""
    if seed not in SEEDS:
        raise ValueError('Nuisance seed not preselected')
    size = annotation['image_size']
    _, uncertain = effective_core(annotation)
    silhouette = polygon_mask(size, [annotation['candidate_procedural_silhouette']])
    core = polygon_mask(size, annotation['opaque_foreground_core_polygons'])
    mask = silhouette | uncertain | core
    # This fixed four-pixel margin is synthetic conservative erasure, not a CI.
    mask = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(9))) > 0
    if np.count_nonzero(~mask) < 64:
        raise ValueError('Insufficient unmasked source background')
    base = np.percentile(rgb[~mask], 70, axis=0)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 1.5, size=(size[1], size[0], 1))
    fill = np.clip(base[None, None, :] + noise, 0, 255)
    blurred = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1.25)), dtype=float) / 255
    weight = np.maximum(blurred, mask.astype(float))
    background = np.rint(rgb.astype(float) * (1 - weight[..., None]) + fill * weight[..., None]).astype(np.uint8)
    return background, mask, {'source_retained_outside_fixed_mask': True,
        'erasure_margin_pixels': 4, 'fill_is_imputed_not_truth': True,
        'fixed_background_seed': seed, 'filled_mask_sha256': sha(mask.tobytes()),
        'background_rgb_sha256': sha(background.tobytes()), 'pixels_erased': int(mask.sum())}

def render_alpha(size, polygon, feather):
    # No RGB patch is rotated: only a procedural polygon is rasterized.
    scale = 4
    im = Image.new('L', (size[0] * scale, size[1] * scale), 0)
    ImageDraw.Draw(im).polygon([tuple(np.asarray(p) * scale) for p in polygon], fill=255)
    im = im.resize(tuple(size), Image.Resampling.LANCZOS)
    if feather:
        im = im.filter(ImageFilter.GaussianBlur(feather))
    return np.asarray(im, dtype=float) / 255

def composite(background, alpha, color):
    if alpha.shape != background.shape[:2] or not np.isfinite(alpha).all() or np.any((alpha < 0) | (alpha > 1)):
        raise ValueError('Invalid alpha')
    return np.rint(background.astype(float) * (1 - alpha[..., None]) + np.asarray(color)[None, None, :] * alpha[..., None]).clip(0, 255).astype(np.uint8)

def prepare_nuisance(rgb, annotation, seed):
    idx = SEEDS.index(seed)
    background, erased, meta = make_background(rgb, annotation, seed)
    color = (foreground_color(rgb, annotation) * (0.90, 1.0, 1.10)[idx]).clip(0, 255)
    return {'background': background, 'erased': erased, 'color': color,
        'feather': (0.0, 0.30, 0.60)[idx], 'meta': meta}

def render(nuisance, cal, annotation, target):
    polygon, geometry = moved_polygon(cal, annotation, target)
    alpha = render_alpha(annotation['image_size'], polygon, nuisance['feather'])
    output = composite(nuisance['background'], alpha, nuisance['color'])
    return output, alpha, geometry
