import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import Dataset as TorchDataset

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    logger.warning("PyTorch not available — TransformerPredictor will raise on use")

_MIN_SEQUENCE_LENGTH = 10
_DEFAULT_PATIENCE = 10


if _TORCH_AVAILABLE:

    class TimeSeriesDataset(TorchDataset):
        def __init__(self, data: np.ndarray, seq_len: int, horizon: int = 1) -> None:
            self._data = torch.from_numpy(data).float()
            self._seq_len = seq_len
            self._horizon = horizon

        def __len__(self) -> int:
            return max(0, len(self._data) - self._seq_len - self._horizon + 1)

        def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
            x = self._data[idx : idx + self._seq_len]
            y = self._data[idx + self._seq_len : idx + self._seq_len + self._horizon, 0]
            return x, y

    class _TransformerModel(nn.Module):
        def __init__(
            self,
            input_dim: int,
            d_model: int,
            nhead: int,
            num_layers: int,
            dropout: float,
            horizon: int,
        ) -> None:
            super().__init__()
            self._input_proj = nn.Linear(input_dim, d_model)
            self._pos_enc = _PositionalEncoding(d_model, dropout)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=nhead,
                dim_feedforward=d_model * 4,
                dropout=dropout,
                batch_first=True,
            )
            self._encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
            self._head = nn.Linear(d_model, horizon)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            h = self._input_proj(x)
            h = self._pos_enc(h)
            h = self._encoder(h)
            out = h[:, -1, :]
            return self._head(out)

    class _PositionalEncoding(nn.Module):
        def __init__(self, d_model: int, dropout: float, max_len: int = 5000) -> None:
            super().__init__()
            self._dropout = nn.Dropout(p=dropout)
            pe = torch.zeros(max_len, d_model)
            position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
            div_term = torch.exp(
                torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model)
            )
            pe[:, 0::2] = torch.sin(position * div_term)
            pe[:, 1::2] = torch.cos(position * div_term)
            pe = pe.unsqueeze(0)
            self.register_buffer("_pe", pe)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            x = x + self._pe[:, : x.size(1)]
            return self._dropout(x)


class TransformerPredictor:

    def __init__(
        self,
        input_dim: int,
        d_model: int = 64,
        nhead: int = 4,
        num_layers: int = 3,
        dropout: float = 0.1,
        seq_len: int = 30,
        horizon: int = 1,
    ) -> None:
        if not _TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required for TransformerPredictor but not installed")

        self._input_dim = input_dim
        self._d_model = d_model
        self._nhead = nhead
        self._num_layers = num_layers
        self._dropout = dropout
        self._seq_len = seq_len
        self._horizon = horizon
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._model: Optional[_TransformerModel] = None
        self._best_state: Optional[dict] = None

        logger.info(
            "TransformerPredictor initialised: input_dim=%d d_model=%d nhead=%d layers=%d device=%s",
            input_dim, d_model, nhead, num_layers, self._device,
        )

    def _build_model(self) -> "nn.Module":
        model = _TransformerModel(
            input_dim=self._input_dim,
            d_model=self._d_model,
            nhead=self._nhead,
            num_layers=self._num_layers,
            dropout=self._dropout,
            horizon=self._horizon,
        )
        return model.to(self._device)

    def train(
        self,
        train_data: np.ndarray,
        val_data: np.ndarray,
        epochs: int = 50,
        lr: float = 1e-3,
        batch_size: int = 32,
        patience: int = _DEFAULT_PATIENCE,
    ) -> dict:
        if self._model is None:
            self._model = self._build_model()

        train_ds = TimeSeriesDataset(train_data, self._seq_len, self._horizon)
        val_ds = TimeSeriesDataset(val_data, self._seq_len, self._horizon)

        if len(train_ds) < 1 or len(val_ds) < 1:
            raise ValueError(
                f"Insufficient data: train_samples={len(train_ds)} val_samples={len(val_ds)}. "
                f"Need at least seq_len({self._seq_len}) + horizon({self._horizon}) rows."
            )

        train_loader = torch.utils.data.DataLoader(
            train_ds, batch_size=batch_size, shuffle=True, drop_last=False
        )
        val_loader = torch.utils.data.DataLoader(
            val_ds, batch_size=batch_size, shuffle=False, drop_last=False
        )

        optimizer = torch.optim.AdamW(self._model.parameters(), lr=lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
        criterion = nn.MSELoss()

        best_val_loss = float("inf")
        patience_counter = 0
        history: dict[str, list[float]] = {"train_loss": [], "val_loss": []}

        for epoch in range(1, epochs + 1):
            self._model.train()
            train_loss = 0.0
            n_batches = 0
            for x_batch, y_batch in train_loader:
                x_batch = x_batch.to(self._device)
                y_batch = y_batch.to(self._device)

                optimizer.zero_grad()
                pred = self._model(x_batch)
                loss = criterion(pred, y_batch)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self._model.parameters(), max_norm=1.0)
                optimizer.step()

                train_loss += loss.item()
                n_batches += 1

            avg_train = train_loss / max(n_batches, 1)

            val_loss = 0.0
            val_batches = 0
            self._model.eval()
            with torch.no_grad():
                for x_batch, y_batch in val_loader:
                    x_batch = x_batch.to(self._device)
                    y_batch = y_batch.to(self._device)
                    pred = self._model(x_batch)
                    val_loss += criterion(pred, y_batch).item()
                    val_batches += 1

            avg_val = val_loss / max(val_batches, 1)
            scheduler.step()

            history["train_loss"].append(avg_train)
            history["val_loss"].append(avg_val)

            if avg_val < best_val_loss:
                best_val_loss = avg_val
                patience_counter = 0
                self._best_state = {k: v.clone() for k, v in self._model.state_dict().items()}
            else:
                patience_counter += 1

            if epoch % 10 == 0 or epoch == 1:
                logger.info(
                    "Epoch %d/%d  train_loss=%.6f  val_loss=%.6f  best_val=%.6f  patience=%d/%d",
                    epoch, epochs, avg_train, avg_val, best_val_loss, patience_counter, patience,
                )

            if patience_counter >= patience:
                logger.info("Early stopping at epoch %d — val_loss not improving for %d epochs", epoch, patience)
                break

        if self._best_state is not None:
            self._model.load_state_dict(self._best_state)
            logger.info("Restored best model with val_loss=%.6f", best_val_loss)

        return {
            "train_loss": history["train_loss"],
            "val_loss": history["val_loss"],
            "best_val_loss": best_val_loss,
            "epochs_run": len(history["train_loss"]),
        }

    def predict(self, data: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Model not trained — call train() first")

        self._model.eval()
        with torch.no_grad():
            if len(data) < self._seq_len:
                raise ValueError(f"Data length {len(data)} < seq_len {self._seq_len}")

            x = torch.from_numpy(data[-self._seq_len:]).float().unsqueeze(0).to(self._device)
            pred = self._model(x)
            return pred.cpu().numpy().flatten()

    def save_model(self, path: str) -> None:
        if self._model is None:
            raise RuntimeError("No model to save")

        save_path = Path(path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "model_state": self._model.state_dict(),
                "config": {
                    "input_dim": self._input_dim,
                    "d_model": self._d_model,
                    "nhead": self._nhead,
                    "num_layers": self._num_layers,
                    "dropout": self._dropout,
                    "seq_len": self._seq_len,
                    "horizon": self._horizon,
                },
            },
            save_path,
        )
        logger.info("Model saved to %s", save_path)

    def load_model(self, path: str) -> None:
        if not _TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required but not installed")

        checkpoint = torch.load(path, map_location=self._device, weights_only=False)
        config = checkpoint["config"]
        self._input_dim = config["input_dim"]
        self._d_model = config["d_model"]
        self._nhead = config["nhead"]
        self._num_layers = config["num_layers"]
        self._dropout = config["dropout"]
        self._seq_len = config["seq_len"]
        self._horizon = config["horizon"]

        self._model = self._build_model()
        self._model.load_state_dict(checkpoint["model_state"])
        self._model.eval()
        logger.info("Model loaded from %s", path)
