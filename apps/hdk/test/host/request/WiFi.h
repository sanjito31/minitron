#pragma once
constexpr int WL_CONNECTED = 3;
struct WiFiStub { int status(); };
extern WiFiStub WiFi;
