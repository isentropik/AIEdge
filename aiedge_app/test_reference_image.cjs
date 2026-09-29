const {test}=require('node:test');
const assert=require('node:assert/strict');
const {load}=require('./reference-image.js');
class ImageFixture {
 static instances=[];
 constructor(){ImageFixture.instances.push(this);}
 set src(value){this.address=value;}
 removeAttribute(name){assert.equal(name,'src');this.address=null;this.canceled=true;}
}
test('successful reference load cleans up handlers and preserves the image',async()=>{
 const pending=load('/reference/example',{ImageType:ImageFixture,timeout:100});
 const image=ImageFixture.instances.at(-1);image.onload();
 assert.equal(await pending,image);assert.equal(image.address,'/reference/example');
 assert.equal(image.onload,null);assert.equal(image.onerror,null);
});
test('failed reference load cancels the source and returns an actionable error',async()=>{
 const pending=load('/reference/example',{ImageType:ImageFixture,timeout:100});
 const image=ImageFixture.instances.at(-1);image.onerror();
 await assert.rejects(pending,/Use Refresh/);assert.equal(image.canceled,true);
 assert.equal(image.onload,null);assert.equal(image.onerror,null);
});
test('a stalled reference times out and cannot resolve from a late callback',async()=>{
 const pending=load('/reference/example',{ImageType:ImageFixture,timeout:10});
 const image=ImageFixture.instances.at(-1),late=image.onload;
 await assert.rejects(pending,/timed out/);late();
 assert.equal(image.canceled,true);assert.equal(image.onload,null);
});
