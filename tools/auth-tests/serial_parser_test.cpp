#include "WebsiteSerialParser.h"
#include <cassert>
#include <string>
#include <vector>
using namespace AIEdgeAuth;
int main(){SerialParser p;std::vector<std::string> got;auto input=[&](const std::string&s){for(unsigned char b:s)p.feed(b,[&](const char*line){got.emplace_back(line);});};
 input("AIEdge AUTH ");assert(got.empty());input("RESET\r\n");assert(got.size()==1&&got.back()=="AIEdge AUTH RESET");
 input("AIEdge AUTH CONFIRM 1234\n");assert(got.size()==2);
 input(" AIEdge AUTH RESET\n");input("HTTP POST /auth/reset\n");assert(got.size()==2);
 input(std::string("AIEdge AUTH ")+std::string(200,'x')+"\n");assert(got.size()==2);
 input(std::string("binary\0AIEdge AUTH RESET\n",25));assert(got.size()==2);
 input("\nAIEdge AUTH SETUP\n");assert(got.size()==3&&got.back()=="AIEdge AUTH SETUP");
 input("AIEdge AUTH RES");p.reset();input("ET\n");assert(got.size()==3);
}
