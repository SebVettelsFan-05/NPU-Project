import numpy as np

def _splitArr(pixelArr):
    useArr = np.array(pixelArr)
    pad_y = (7 - (useArr.shape[0] % 7)) % 7
    pad_x = (7 - (useArr.shape[1] % 7)) % 7
    padded_matrix = np.pad(useArr, ((0, pad_y), (0, pad_x)), mode='constant', constant_values=0)
    Y_new, X_new = padded_matrix.shape
    dataunit = padded_matrix.reshape(Y_new // 7, 7, X_new // 7, 7).swapaxes(1,2)
    return dataunit, Y_new, X_new

def _sendArr(dataunit):
    for y_blocks in range(dataunit.shape[0]):
        for x_blocks in range(dataunit.shape[1]):
            currentstream = dataunit[y_blocks, x_blocks]
            print(currentstream)
    return

