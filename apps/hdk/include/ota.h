#pragma once

#define HOSTNAME        "minitron"
#define PORT            3232

int init_ota();
void handle_ota();
bool ota_update_in_progress();
