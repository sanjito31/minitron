#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>

// MatrixPanel_I2S_DMA display
MatrixPanel_I2S_DMA *dma_display    = nullptr;


int init_display()
{
        // Initialize RGB LED Matrix Display
  	Serial.println("Initializing display...");
	
        HUB75_I2S_CFG mxconfig(
		MATRIX_WIDTH,
		MATRIX_HEIGHT,
		CHAIN_LENGTH
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