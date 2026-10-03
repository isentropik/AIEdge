"""Texture-based marker proposals outside configured dials; never automatic calibration."""
from itertools import combinations
import numpy as np
from calibration_builder import image_rgb,box

WIDTH,HEIGHT=40,32
MARGIN=32
MIN_DISTANCE=128
MIN_AREA=12288

def propose(reference,crops,visible=None):
    if not isinstance(crops,list) or not 1<=len(crops)<=16:raise ValueError('Add dial crops before suggesting markers.')
    crops=[box(crop,148) for crop in crops]
    gray=np.asarray(image_rgb(reference).convert('L'),dtype=np.float64)
    blocked=np.zeros((480,640),dtype=np.uint8)
    for x,y,w,h in crops:blocked[max(0,y-4):min(480,y+h+4),max(0,x-4):min(640,x+w+4)]=1
    candidates=[]
    for y in range(MARGIN,480-MARGIN-HEIGHT+1,8):
        for x in range(MARGIN,640-MARGIN-WIDTH+1,8):
            if visible is not None and not visible.contains_box([x,y,WIDTH,HEIGHT]):continue
            if blocked[y:y+HEIGHT,x:x+WIDTH].any():continue
            patch=gray[y:y+HEIGHT,x:x+WIDTH]
            if np.mean((patch<8)|(patch>247))>.3:continue
            spread=float(patch.std())
            gx=float(np.mean(np.abs(np.diff(patch,axis=1))))
            gy=float(np.mean(np.abs(np.diff(patch,axis=0))))
            if spread<14 or min(gx,gy)<3 or max(gx,gy)<6:continue
            score=min(spread,60)+2*min(gx,gy)
            candidates.append((score,[x,y,WIDTH,HEIGHT]))
    # Keep separated texture peaks before testing spatially useful triples.
    peaks=[]
    for score,candidate in sorted(candidates,key=lambda item:(-item[0],item[1][1],item[1][0])):
        if all((candidate[0]-prior[1][0])**2+(candidate[1]-prior[1][1])**2>=64**2 for prior in peaks):
            peaks.append((score,candidate))
            if len(peaks)==24:break
    chosen=None;best=-1
    for trio in combinations(peaks,3):
        centers=[(row[1][0]+WIDTH/2,row[1][1]+HEIGHT/2) for row in trio]
        if any((a[0]-b[0])**2+(a[1]-b[1])**2<MIN_DISTANCE**2 for a,b in combinations(centers,2)):continue
        a,b,c=centers;area=abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/2
        if area<MIN_AREA:continue
        score=sum(row[0] for row in trio)*(0.5+area/(640*480))
        if score>best:chosen=trio;best=score
    if chosen is None:return {'markers':[],'reason':'No three separated textured areas were found outside the dial crops. Place markers manually.','automatic_calibration':False}
    markers=sorted([row[1] for row in chosen],key=lambda row:(row[1],row[0]))
    return {'markers':markers,'reason':'Check that each box covers fixed printed markings, not reflections or moving parts.','automatic_calibration':False}
