#pragma once
#include <cstdint>
#include <ctime>
#include <string>

namespace SavedReadingTime {
// Current files include %z; old files may omit it. Never normalize bad dates.
inline bool parse(const std::string& text, std::time_t& result) {
    if (text.size()!=19 && text.size()!=20 && text.size()!=24) return false;
    if (text[4]!='-' || text[7]!='-' || text[10]!='T' || text[13]!=':' || text[16]!=':') return false;
    auto digits=[&](size_t at,size_t count) {
        int value=0;
        for(size_t i=at;i<at+count;++i) {
            if(text[i]<'0'||text[i]>'9')return -1;
            value=value*10+text[i]-'0';
        }
        return value;
    };
    const int year=digits(0,4),month=digits(5,2),day=digits(8,2);
    const int hour=digits(11,2),minute=digits(14,2),second=digits(17,2);
    if(year<1970||month<1||month>12||day<1||hour<0||hour>23||minute<0||minute>59||second<0||second>59)return false;
    const bool leap=year%4==0&&(year%100!=0||year%400==0);
    const int lengths[]={31,28,31,30,31,30,31,31,30,31,30,31};
    if(day>lengths[month-1]+(month==2&&leap?1:0))return false;
    if(text.size()==19) {
        std::tm local{};
        local.tm_year=year-1900;local.tm_mon=month-1;local.tm_mday=day;
        local.tm_hour=hour;local.tm_min=minute;local.tm_sec=second;local.tm_isdst=-1;
        const std::time_t parsed=std::mktime(&local);
        if(parsed==std::time_t(-1)||local.tm_year!=year-1900||local.tm_mon!=month-1||local.tm_mday!=day||local.tm_hour!=hour||local.tm_min!=minute||local.tm_sec!=second)return false;
        result=parsed;return true;
    }
    int offset=0;
    if(text.size()==20) {if(text[19]!='Z')return false;}
    else {
        if(text[19]!='+'&&text[19]!='-')return false;
        const int hours=digits(20,2),minutes=digits(22,2);
        if(hours<0||hours>23||minutes<0||minutes>59)return false;
        offset=(hours*60+minutes)*60*(text[19]=='+'?1:-1);
    }
    auto leaps=[](int y){return y/4-y/100+y/400;};
    int64_t days=int64_t(year-1970)*365+leaps(year-1)-leaps(1969)+day-1;
    for(int m=1;m<month;++m)days+=lengths[m-1]+(m==2&&leap?1:0);
    const int64_t seconds=days*86400+hour*3600+minute*60+second-offset;
    const std::time_t parsed=static_cast<std::time_t>(seconds);
    if(static_cast<int64_t>(parsed)!=seconds)return false;
    result=parsed;return true;
}
}
