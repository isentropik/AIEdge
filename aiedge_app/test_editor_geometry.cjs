const test=require('node:test');
const assert=require('node:assert/strict');
const {corners,nearestCorner,resizeBox,resizeDimension}=require('./editor-geometry.js');
test('small boxes choose the closest corner, not the first overlapping handle',()=>{
 for(const scale of [.25,.5,1,2])for(const box of [[100,100,8,8],[20,30,55,50],[76,245,144,146]])
  corners(box).forEach((p,i)=>assert.equal(nearestCorner(p,box,scale),i));
 assert.equal(nearestCorner([400,300],[10,10,20,20],1),-1);
});
test('corner resizing preserves the opposite anchor',()=>{
 const box=[100,100,100,80];
 corners(box).forEach((p,corner)=>{
  const drag={start:p,box,corner,move:false,ratio:null};
  const result=resizeBox(drag,[p[0]+5,p[1]+7],148);
  assert.deepEqual(corners(result)[(corner+2)%4],corners(box)[(corner+2)%4]);
 });
});
test('moving a crop preserves size and stays within image edges',()=>{
 const drag={box:[100,100,140,130],start:[110,110],move:true};
 assert.deepEqual(resizeBox(drag,[999,999],148),[500,350,140,130]);
 assert.deepEqual(resizeBox(drag,[-99,-99],148),[0,0,140,130]);
});
test('locked pointer resizing preserves proportions with pixel rounding',()=>{
 const box=[200,200,80,100];
 for(let corner=0;corner<4;corner++)for(let x=-200;x<=800;x+=23)for(let y=-200;y<=700;y+=29){
  const b=resizeBox({box,start:corners(box)[corner],corner,move:false,ratio:.8},[x,y],148);
  if(!b)continue;
  assert.ok(b[0]>=0&&b[1]>=0&&b[2]>=8&&b[3]>=8&&b[2]<=148&&b[3]<=148);
  assert.ok(b[0]+b[2]<=640&&b[1]+b[3]<=480);
  assert.ok(Math.abs(b[2]-.8*b[3])<=1);
  const anchor=corners(box)[(corner+2)%4];
  assert.ok(corners(b).some(p=>p[0]===anchor[0]&&p[1]===anchor[1]));
 }
});
test('numeric width and height edits honor the same proportion lock',()=>{
 assert.deepEqual(resizeDimension([100,100,80,100],2,64,148,true),[100,100,64,80]);
 assert.deepEqual(resizeDimension([100,100,80,100],3,120,148,true),[100,100,96,120]);
 assert.equal(resizeDimension([600,100,40,100],2,50,148,true),null);
 assert.equal(resizeDimension([100,100,80,100],2,148,148,true),null);
 assert.equal(resizeDimension([100,100,80,100],2,NaN,148,true),null);
});
