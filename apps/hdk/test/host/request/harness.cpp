#include <HTTPClient.h>
#include <WiFi.h>
#include <algorithm>
#include <cassert>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <sstream>
#include <vector>
#include "request.h"

SerialStub Serial;
WiFiStub WiFi;
WiFiClient stream;
std::vector<uint8_t> fixture, payload;
std::vector<std::string> responses;
std::string mode, endpoint, content_type, accept;
size_t response_index = 0, offset = 0;
unsigned long now = 0;
int random_calls = 0, begins = 0, ends = 0;
bool online = true, ota = false, identity_available = true, active = false;

int WiFiStub::status() { return online ? WL_CONNECTED : 0; }
bool ota_update_in_progress() { return ota; }
const char *get_device_id() {
    return identity_available ? "550e8400-e29b-41d4-a716-446655440000" : nullptr;
}
unsigned long millis() { return now; }
void delay(unsigned long ms) {
    now += ms;
    if ((mode == "ota_validation" && ms == 1) ||
        (mode == "ota_backoff" && ms == 500)) ota = true;
}
void *ps_malloc(size_t size) { return std::malloc(size); }
void esp_fill_random(void *out, size_t size) {
    ++random_calls;
    for (size_t i = 0; i < size; ++i)
        static_cast<uint8_t *>(out)[i] = static_cast<uint8_t>(random_calls + i);
}

bool HTTPClient::begin(const String &url) {
    assert(!active);
    active = true;
    ++begins;
    mode = responses[std::min(response_index++, responses.size() - 1)];
    endpoint = url;
    content_type.clear();
    accept.clear();
    offset = 0;
    payload = fixture;
    if (mode == "invalid") payload = {'n', 'o', 't', ' ', 'W', 'e', 'b', 'P'};
    if (mode == "short_read" || mode == "truncated_webp")
        payload.resize(payload.size() / 2);
    if (mode == "corrupt_frame") {
        // Keep the animation container and frame headers, corrupt the last frame's pixels.
        const std::string data(payload.begin(), payload.end());
        size_t last = data.rfind("VP8L");
        assert(last != std::string::npos);
        size_t frame_size = payload[last + 4] | (payload[last + 5] << 8) |
                            (payload[last + 6] << 16) | (payload[last + 7] << 24);
        std::fill(payload.begin() + last + 13,
                  payload.begin() + last + 8 + frame_size, 0);
    }
    return mode != "begin_error";
}
void HTTPClient::addHeader(const String &name, const String &value) {
    if (name == "Content-Type") content_type = value;
    if (name == "Accept") accept = value;
}
int HTTPClient::POST(String body) {
    std::cout << "post|" << endpoint << '|' << body << '|' << content_type << '|' << accept << '\n';
    if (mode == "http_error" || mode == "ota_backoff") return 500;
    if (mode == "transport_error") return -1;
    if (mode == "header_timeout") now += 16000;
    return HTTP_CODE_OK;
}
int HTTPClient::getSize() {
    if (mode == "unknown_length") return -1;
    if (mode == "zero_length") return 0;
    return static_cast<int>(mode == "short_read" ? fixture.size() : payload.size());
}
WiFiClient *HTTPClient::getStreamPtr() { return &stream; }
bool HTTPClient::connected() { return mode == "stall" || offset < payload.size(); }
void HTTPClient::end() {
    assert(active);
    active = false;
    ++ends;
}
size_t WiFiClient::available() {
    if (mode == "stall") return 0;
    return std::min<size_t>(127, payload.size() - offset);
}
int WiFiClient::read(uint8_t *out, size_t length) {
    if (mode == "read_error") return -1;
    std::memcpy(out, payload.data() + offset, length);
    offset += length;
    if (mode == "ota_download") ota = true;
    if (mode == "wifi_download") online = false;
    return static_cast<int>(length);
}

int main(int argc, char **argv) {
    assert(argc >= 3);
    std::ifstream input(argv[1], std::ios::binary);
    assert(input.good());
    fixture.assign(std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>());
    for (int cycle = 2; cycle < argc; ++cycle) {
        std::string plan = argv[cycle];
        online = plan != "offline";
        ota = plan == "ota_idle";
        identity_available = plan != "no_device_id";
        mode.clear();
        responses.clear();
        response_index = 0;
        std::istringstream plans(plan);
        for (std::string item; std::getline(plans, item, ',');) responses.push_back(item);
        uint8_t *buffer = reinterpret_cast<uint8_t *>(1);
        size_t length = 99;
        const int result = requestGraphic("http://server", &buffer, &length);
        if (result == 0) {
            assert(length == fixture.size());
            assert(std::memcmp(buffer, fixture.data(), length) == 0);
            std::free(buffer);
        } else {
            assert(buffer == nullptr && length == 0);
        }
        assert(!active && begins == ends);
        std::cout << "cycle|" << result << '|' << length << '|' << random_calls
                  << '|' << begins << '|' << ends << '|' << now << '\n';
        // The real polling task waits ten seconds before calling again.
        now += 10000;
    }
}
