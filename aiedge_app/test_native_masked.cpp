#include "native.cpp"
#include <cassert>
#include <iostream>
int main(){
 std::vector<uint8_t> rgb(640*480*3,180);RuntimeProfile p;
 int xs[3]={60,300,540},ys[3]={60,60,400};
 uint32_t seed=12345;
 for(int k=0;k<3;k++){p.pixels[k].resize(16*16);for(int j=0;j<256;j++){seed=1664525*seed+1013904223;p.pixels[k][j]=seed>>24;int x=xs[k]+j%16,y=ys[k]+j/16;for(int c=0;c<3;c++)rgb[(y*640+x)*3+c]=p.pixels[k][j];}p.markers.markers[k]={p.pixels[k].data(),256,16,16,xs[k],ys[k],double(xs[k]),double(ys[k])};}
 for(int i=0;i<6;i++){polar::DialGeometry d{};d.x=100+(i%3)*150;d.y=100+(i/3)*150;d.w=d.h=148;d.inverse[0]=d.inverse[4]=70;d.inverse[2]=d.inverse[5]=74;d.inverse[8]=1;d.pivot[0]=d.pivot[1]=0;polar::ValidatedDialGeometry g(d,d.x,d.y);assert(g.get());p.dials.push_back(g);for(int y=0;y<148;y++)for(int x=0;x<148;x++){uint8_t v=((x/3+y/3)%2)?230:40;for(int c=0;c<3;c++)rgb[((d.y+y)*640+d.x+x)*3+c]=v;}}
 p.cache.resize(6);std::vector<int8_t> a(6*384*40),b(a.size());int sa[6],sb[6],ra[6],rb[6];double va[6],vb[6];uint8_t all[6]={1,1,1,1,1,1},mask[6]={0,0,0,0,1,1};
 int first=aiedge_prepare_profile(&p,rgb.data(),rgb.size(),0,a.data(),a.size(),sa,va,6);std::cout<<"alignment_status="<<first<<"\n";assert(first==0);for(int i=0;i<6;i++)std::cout<<"dial_state["<<i<<"]="<<sa[i]<<"\n";
 assert(aiedge_prepare_profile_masked(&p,rgb.data(),rgb.size(),0,b.data(),b.size(),sb,vb,6,rb,all,6)==0);assert(a==b);for(int i=0;i<6;i++){assert(sa[i]==sb[i]);assert(va[i]==vb[i]);}
 assert(aiedge_prepare_profile_masked(&p,rgb.data(),rgb.size(),0,b.data(),b.size(),sb,vb,6,rb,mask,6)==0);for(int i=0;i<6;i++){if(i<4){assert(sb[i]==-1&&vb[i]==-1&&!p.cache[i].valid);for(int j=0;j<15360;j++)assert(b[i*15360+j]==0);}else{assert(sa[i]==sb[i]&&va[i]==vb[i]);assert(std::memcmp(a.data()+i*15360,b.data()+i*15360,15360)==0);}}
 assert(aiedge_prepare_profile_reuse(&p,rgb.data(),rgb.size(),0,b.data(),b.size(),sb,vb,6,rb)==0);assert(a==b);for(int i=0;i<4;i++)assert(rb[i]==0);
 uint8_t invalid[6]={0,0,0,0,0,2},empty[6]={};assert(aiedge_prepare_profile_masked(&p,rgb.data(),rgb.size(),0,b.data(),b.size(),sb,vb,6,rb,invalid,6)==-1);assert(aiedge_prepare_profile_masked(&p,rgb.data(),rgb.size(),0,b.data(),b.size(),sb,vb,6,rb,empty,6)==-1);assert(aiedge_prepare_profile_masked(&p,rgb.data(),rgb.size(),0,b.data(),b.size(),sb,vb,6,rb,all,5)==-1);
 // Sparse selected bytes must also match legacy path.
 assert(aiedge_prepare_profile(&p,rgb.data(),rgb.size(),1,a.data(),a.size(),sa,va,6)==0);
 assert(aiedge_prepare_profile_masked(&p,rgb.data(),rgb.size(),1,b.data(),b.size(),sb,vb,6,rb,all,6)==0);assert(a==b);for(int i=0;i<6;i++)assert(sa[i]==sb[i]&&va[i]==vb[i]);
 // Selected flat crops reject identically without reusing accepted features.
 for(int i=4;i<6;i++){auto d=p.dials[i].get();for(int y=0;y<148;y++)for(int x=0;x<148;x++)for(int c=0;c<3;c++)rgb[((d->y+y)*640+d->x+x)*3+c]=180;}
 assert(aiedge_prepare_profile(&p,rgb.data(),rgb.size(),0,a.data(),a.size(),sa,va,6)==0);
 assert(aiedge_prepare_profile_masked(&p,rgb.data(),rgb.size(),0,b.data(),b.size(),sb,vb,6,rb,mask,6)==0);for(int i=4;i<6;i++){assert(sa[i]==sb[i]&&va[i]==vb[i]);assert(sa[i]!=int(polar::PreparationStatus::Ok));assert(!p.cache[i].valid);}
 std::fill(rgb.begin(),rgb.end(),0);assert(aiedge_prepare_profile_masked(&p,rgb.data(),rgb.size(),0,b.data(),b.size(),sb,vb,6,rb,mask,6)==-2);for(auto&c:p.cache)assert(!c.valid);
 std::cout<<"PASS synthetic full/all-mask byte-state-visibility parity; partial omission; full-partial-full; invalid masks; unconditional alignment failure/cache invalidation\n";
}
