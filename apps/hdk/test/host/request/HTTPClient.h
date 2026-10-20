#pragma once
#include "Arduino.h"
constexpr int HTTP_CODE_OK = 200;
struct WiFiClient {
    size_t available();
    int read(uint8_t *, size_t);
};
class HTTPClient {
public:
    void setConnectTimeout(int) {}
    void setTimeout(int) {}
    bool begin(const String &);
    void addHeader(const String &, const String &);
    int POST(String);
    int getSize();
    WiFiClient *getStreamPtr();
    bool connected();
    void end();
};
