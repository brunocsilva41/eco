"""VAD Silero (onnx) em CPU. Janelas de 512 amostras a 16 kHz (32 ms)."""
import numpy as np, onnxruntime as ort

class SileroVAD:
    def __init__(self, path=r"F:\Jarvis\models\silero\silero_vad.onnx"):
        so = ort.SessionOptions(); so.inter_op_num_threads = 1; so.intra_op_num_threads = 1
        self.s = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), np.float32)
        self.ctx = np.zeros((1, 64), np.float32)

    def prob(self, chunk_f32):
        """chunk_f32: 512 amostras float32 em [-1,1]. Retorna prob. de fala."""
        x = np.concatenate([self.ctx, chunk_f32.reshape(1, -1)], axis=1)
        out, self.state = self.s.run(None, {"input": x, "state": self.state,
                                            "sr": np.array(16000, np.int64)})
        self.ctx = x[:, -64:]
        return float(out[0][0])
