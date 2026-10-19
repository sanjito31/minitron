#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>

// Custom pin mapping for HUB75 adapter board
#define R1_PIN  18
#define G1_PIN  25
#define B1_PIN   5
#define R2_PIN  17
#define G2_PIN  33
#define B2_PIN  16
#define A_PIN    4
#define B_PIN    3
#define C_PIN    0
#define D_PIN   21
#define E_PIN   32
#define LAT_PIN 19
#define OE_PIN  15
#define CLK_PIN  2

// MatrixPanel_I2S_DMA display
#define MATRIX_WIDTH	64
#define MATRIX_HEIGHT	32

MatrixPanel_I2S_DMA *dma_display    = nullptr;


int init_display()
{
        // Initialize RGB LED Matrix Display
  	Serial.println("Initializing display...");

	HUB75_I2S_CFG::i2s_pins _pins={R1_PIN, G1_PIN, B1_PIN, R2_PIN, G2_PIN, B2_PIN, A_PIN, B_PIN, C_PIN, D_PIN, E_PIN, LAT_PIN, OE_PIN, CLK_PIN};

        HUB75_I2S_CFG mxconfig(
		MATRIX_WIDTH,
		MATRIX_HEIGHT,
		CHAIN_LENGTH,
		_pins
	);

        dma_display = new MatrixPanel_I2S_DMA(mxconfig);
	
        if(!dma_display->begin()) {
		return 1;
	}
	
        dma_display->setBrightness8(50);
	dma_display->clearScreen();
	return 0;
}

void display_draw(const uint8_t *pix, int width, int height, int channels, int ixR, int ixG, int ixB) {
	for (unsigned int i = 0; i < height; i++) {
		for (unsigned int j = 0; j < width; j++) {
			const uint8_t *p = &pix[(i * width + j) * channels];
			uint8_t r = p[ixR];
			uint8_t g = p[ixG];
			uint8_t b = p[ixB];

		dma_display->drawPixelRGB888(j, i, r, g, b);
		}
	}
	dma_display->flipDMABuffer();
}