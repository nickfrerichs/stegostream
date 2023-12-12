import base64, crcmod
import pytesseract
import numpy as np
from PIL import Image, ImageFont, ImageDraw
import cv2
import os


DELIMITER = "-"
VALID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"+DELIMITER
DEBUG_IMAGE_PATH = "./temp/debug_images"

width, height = 1280, 720  # Set your desired dimensions
org = (100, 50)

font_path = './DejaVuSerif.ttf'  # Replace with the path to your TTF font file
font_path = './verdana.ttf'
font_path = './Courier New Regular.ttf'
font_size = 60
font_color = (0, 0, 0)  # Black color

# Load TTF font using Pillow
font_pil = ImageFont.truetype(font_path, font_size)


class Codec:

    # Raw data in, return an image
    def encode(self, raw_data):
        base32_data = base64.b32encode(raw_data.encode("ascii")).decode("ascii").replace("=","")
        crc = self.__getCRC(base32_data)  

        line = (base32_data+DELIMITER+crc).replace("=","")
        # with open("./send.log","a") as f:
        #     f.write(line+"\n")

        base_img = np.ones((height, width, 3), np.uint8) * 255  # 3 channels for RGB, filled with white
        
        # Convert OpenCV image to Pillow image
        image_pil = Image.fromarray(cv2.cvtColor(base_img, cv2.COLOR_BGR2RGB))

        # Create a drawing object
        draw = ImageDraw.Draw(image_pil)

        # Draw text on the image using Pillow
        draw.text(org, line, font=font_pil, fill=font_color)

        # Convert back to OpenCV format
        img = cv2.cvtColor(np.array(image_pil), cv2.COLOR_RGB2BGR)
        return img


        
    def __getCRC(self, input_string):
        # Returns CRC value as Base32
        crc8 = crcmod.predefined.Crc('crc-8')
        crc8.update(input_string.encode('utf-8'))
        crc_bytes = crc8.crcValue.to_bytes(1, byteorder='big')
        base32_value = base64.b32encode(crc_bytes)
        return base32_value.decode().replace("=","")



    # Encoded image in, return (error=true/false, data)
    def decode(self, image):
        ocr_functions = [
            self.__ocrL1,
            self.__ocrL2
        ]
        data = ""
        crc = ""
        raw_data = ""
        attempt = 0

        image = image[25:700]

        for ocr_func in ocr_functions:
            raw_data = ocr_func(image)
            attempt += 1

            try:
                data, crc = raw_data.split(DELIMITER,1)
            except:
                #print("OCR found no CRC - $")
                continue
            
            if crc == self.__getCRC(data):
                # print(raw_data+" CRC Match - Attempt "+str(attempt))
                return (True, data, (crc, raw_data, attempt))
            #else:
                # print(result+" - "+data+" - "+self.__getCRC(data))

        return (False, data, (crc, raw_data, attempt))


    def __ocrL1(self, image):
        result = pytesseract.image_to_string(image, config="--psm 6 -c tessedit_char_whitelist="+VALID_CHARS).strip()        
        return result


    def __ocrL2(self, image):
        # # Thresholding
        _, img_threshold = cv2.threshold(image, 128, 255, cv2.THRESH_BINARY)
        image = img_threshold
        # # Denoising
        image = cv2.medianBlur(img_threshold, 5)  # Adjust the kernel size as needed
        result = pytesseract.image_to_string(image, config="--psm 6 nobatch -l osd -c tessedit_char_whitelist="+VALID_CHARS).strip()
        print("IN level 2")
        return result


    def debug(self, is_valid, msg_data, data, img, filename):

        # Temp for debugging
        org = (50, 200)
        font = cv2.FONT_HERSHEY_DUPLEX
        fontScale = 1
        color = (0, 0, 0)
        thickness = 2

        img = cv2.putText(img, data[1], org, font, fontScale, color, thickness)
        cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH,str(filename)+".bmp"),img)
