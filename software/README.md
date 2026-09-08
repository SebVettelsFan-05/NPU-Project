Will be used to keep track of software

SW directory --> all software running on a computer
    this includes all code to emulate what is run on the firmware


    what will be run:
        1. python file emulator
            input: PNG File
            Confirm: image size
            Convert it to greyscale
            process image file --> handle all headers
            process into 4 bit pieces
            section off into 7x7 pixel
            remember each section, load output into ram and reconstruct png

Computer only section
    1. input image --> DONE
        a. convert.py
            _convert($IMAGEPATH) --> checks for convert command, then attempts to convert any PNG image to 4 bit grayscale
Computer MCU shared:
    1. greyscale input 
        a. enforce.py --> enforce dependencies --> DONE
            _enforce() --> open png as binary, load it into $data --> DONE
            _check_signature() --> read first 8 bytes, if it doesnt have the header return false, else return true --> DONE
        b. read.py --> read off of the png, load an array into RAM --> INC
            _read_chunks(data) --> separate png into chunks, big endian --> return chunks --> DONE
                i) _read_chunks(data) --> DONE
                    skip first 8 bytes
                    identify:
                                    [
                                        (b'IHDR', ...), --> this is the data portion --> lots of metadata here
                                                               Width:              4 bytes --> img dimensions in pixels
                                                               Height:             4 bytes --> img dimensions in pixels
                                                               Bit depth:          1 byte  --> bits per sample --> expected value is 4 here(valid grayscale are 1,2,4,8,16)
                                                               Color type:         1 byte  --> iterpretation of color data --> expect a 0 here for grayscale
                                                               Compression method: 1 byte  --> method to compress data --> expect 0, 
                                                                                               which is deflate/inflate compression with a sliding window of at most 32768 bytes)
                                                               Filter method:      1 byte
                                                               Interlace method:   1 byte
                                        (b'bKGD', ...), --> this is background, default...?
                                        (b'pHYs', ...), --> pixel size
                                        (b'tIME', ...), --> last modified, 7 bytes
                                        (b'IDAT', ...), --> actual image data
                                        (b'IDAT', ...), --> actual image data.. as many of these as we need
                                        (b'IEND', ...)  --> end of PNG
                                    ]
                ii) _read_ihdr(chunks) --> read IHDR Data --> DONE
                        expected data: 
                        Width:              4 bytes
                        Height:             4 bytes
                        Bit depth:          1 byte
                        Color type:         1 byte
                        Compression method: 1 byte
                        Filter method:      1 byte
                        Interlace method:   1 byte
                iii) _get_idat(chunks) --> get the actual compressed data --> DONE
                iv) _decompress(idatdata) --> actually decompresses the data --> DONE
                v) _decode_scanlines --> each data still has a filter byte, so need to remove it, gets each row --> INC
                vi) _unfilter_row() --> remove filter byte --> INC
                vii) _paeth() --> filter type 4 work  --> INC
                viii) _unpack_pixels --> actually get the pixels --> INC
                ix) read_png() --> tie it all together --> INC
    2. RAM data structure --> read into 7x7 chunks --> DNS
        a. de
            
