"""Build calibration from explicit image landmarks; never guess a needle pivot."""
import base64,hashlib,io,math
import numpy as np
from PIL import Image
from calibration import validate,finite_number

def image_rgb(blob):
    if not 4<=len(blob)<=4*1024*1024:raise ValueError('reference_image_size_invalid')
    try:
        with Image.open(io.BytesIO(blob)) as im:
            if im.format not in ('JPEG','PNG') or im.size!=(640,480):raise ValueError('reference_must_be_640x480')
            im.load();return im.convert('RGB')
    except (OSError,Image.DecompressionBombError):
        raise ValueError('reference_image_unreadable') from None

def point(value):
    if not isinstance(value,list) or len(value)!=2 or any(not finite_number(v) for v in value):raise ValueError('invalid_landmark')
    if not 0<=value[0]<640 or not 0<=value[1]<480:raise ValueError('landmark_outside_frame')
    return np.array(value,dtype=float)

def box(value,maximum):
    if not isinstance(value,list) or len(value)!=4 or any(type(v) is not int for v in value):raise ValueError('invalid_box')
    x,y,w,h=value
    if not (8<=w<=maximum and 8<=h<=maximum and 0<=x<=640-w and 0<=y<=480-h):raise ValueError('box_outside_supported_bounds')
    return value

def dial_geometry(spec):
    if not isinstance(spec,dict):raise ValueError('invalid_dial_geometry')
    x,y,w,h=box(spec['crop'],148)
    if not isinstance(spec.get('rim_points'),list) or len(spec['rim_points'])!=4:raise ValueError('four_rim_landmarks_required')
    points=np.array([point(v)-[x,y] for v in spec['rim_points']])
    pivot=point(spec['needle_pivot'])-[x,y]
    if np.any(points<0) or np.any(points[:,0]>=w) or np.any(points[:,1]>=h) or np.any(pivot<0) or pivot[0]>=w or pivot[1]>=h:raise ValueError('landmark_outside_crop')
    # Clockwise in image coordinates. Reject crossed, repeated and almost-collinear outlines.
    for i in range(4):
        a=points[(i+1)%4]-points[i];b=points[(i+2)%4]-points[(i+1)%4]
        if a[0]*b[1]-a[1]*b[0]<4:raise ValueError('rim_landmarks_must_be_clockwise_and_convex')
    src=((0,-1),(1,0),(0,1),(-1,0));matrix=[];target=[]
    for (u,v),(px,py) in zip(src,points):
        matrix.extend([[u,v,1,0,0,0,-px*u,-px*v],[0,0,0,u,v,1,-py*u,-py*v]]);target.extend([px,py])
    matrix=np.asarray(matrix)
    if np.linalg.cond(matrix)>1e10:raise ValueError('dial_geometry_ill_conditioned')
    try:
        inverse=np.append(np.linalg.solve(matrix,target),1).reshape(3,3)
        normalized=np.linalg.solve(inverse,np.append(pivot,1))
    except np.linalg.LinAlgError:raise ValueError('dial_geometry_singular') from None
    if abs(normalized[2])<1e-12:raise ValueError('pivot_projection_invalid')
    normalized=normalized[:2]/normalized[2]
    return {'name':spec['name'],'model':spec['model'],'direction':spec['direction'],'crop':[x,y,w,h],
            'sampling_anchor':[x,y],'inverse':inverse.flatten().tolist(),'pivot':normalized.tolist(),
            'landmarks':{'rim_points':spec['rim_points'],'needle_pivot':spec['needle_pivot']}}

def build(reference,design):
    if not isinstance(design,dict):raise ValueError('invalid_setup_design')
    if not isinstance(design.get('markers'),list) or len(design['markers'])!=3:raise ValueError('three_markers_required')
    if not isinstance(design.get('dials'),list) or not 1<=len(design['dials'])<=16:raise ValueError('invalid_dial_count')
    image=image_rgb(reference);gray=image.convert('L');markers=[]
    for candidate in design['markers']:
        x,y,w,h=box(candidate,128);pixels=gray.crop((x,y,x+w,y+h)).tobytes()
        markers.append({'box':[x,y,w,h],'target':[x+w/2,y+h/2],'pixels':base64.b64encode(pixels).decode(),
                        'sha256':hashlib.sha256(pixels).hexdigest()})
    document={'version':1,'image_size':[640,480],'reference_sha256':hashlib.sha256(reference).hexdigest(),
              'markers':markers,'dials':[dial_geometry(d) for d in design['dials']]}
    return validate(document)
