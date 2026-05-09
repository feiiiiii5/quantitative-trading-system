__all__ = [
    "POLARS_AVAILABLE",
    "fast_read_csv",
    "fast_read_parquet",
    "fast_groupby_agg",
    "fast_cross_section",
    "pl",
]

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import polars as pl

    POLARS_AVAILABLE = True
except ImportError:
    pl = None
    POLARS_AVAILABLE = False


def fast_read_csv(
    path: str | Path,
    columns: list[str] | None = None,
    dtypes: dict[str, type] | None = None,
) -> pd.DataFrame:
    if not POLARS_AVAILABLE:
        return pd.read_csv(path, usecols=columns, dtype=dtypes)

    try:
        lf = pl.scan_csv(path)
        if columns:
            lf = lf.select(columns)
        df = lf.collect()
        return df.to_pandas()
    except Exception as e:
        logger.debug("Polars CSV read failed, falling back to pandas: %s", e)
        return pd.read_csv(path, usecols=columns, dtype=dtypes)


def fast_read_parquet(
    path: str | Path,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    if not POLARS_AVAILABLE:
        return pd.read_parquet(path, columns=columns)

    try:
        lf = pl.scan_parquet(path)
        if columns:
            lf = lf.select(columns)
        df = lf.collect()
        return df.to_pandas()
    except Exception as e:
        logger.debug("Polars Parquet read failed, falling back to pandas: %s", e)
        return pd.read_parquet(path, columns=columns)


def fast_groupby_agg(
    df: pd.DataFrame,
    group_cols: list[str],
    agg_dict: dict[str, list[str]],
) -> pd.DataFrame:
    if not POLARS_AVAILABLE or df.empty:
        result = df.groupby(group_cols).agg(agg_dict)
        result.columns = ["_".join(col).strip("_") for col in result.columns.values]
        return result.reset_index()

    try:
        pl_df = pl.from_pandas(df)
        exprs = []
        for col, funcs in agg_dict.items():
            for func in funcs:
                if func == "mean":
                    exprs.append(pl.col(col).mean().alias(f"{col}_mean"))
                elif func == "sum":
                    exprs.append(pl.col(col).sum().alias(f"{col}_sum"))
                elif func == "std":
                    exprs.append(pl.col(col).std().alias(f"{col}_std"))
                elif func == "min":
                    exprs.append(pl.col(col).min().alias(f"{col}_min"))
                elif func == "max":
                    exprs.append(pl.col(col).max().alias(f"{col}_max"))
                elif func == "count":
                    exprs.append(pl.col(col).count().alias(f"{col}_count"))
                elif func == "median":
                    exprs.append(pl.col(col).median().alias(f"{col}_median"))
                elif func == "first":
                    exprs.append(pl.col(col).first().alias(f"{col}_first"))
                elif func == "last":
                    exprs.append(pl.col(col).last().alias(f"{col}_last"))
        result = pl_df.group_by(group_cols).agg(exprs)
        return result.to_pandas()
    except Exception as e:
        logger.debug("Polars groupby failed, falling back to pandas: %s", e)
        result = df.groupby(group_cols).agg(agg_dict)
        result.columns = ["_".join(col).strip("_") for col in result.columns.values]
        return result.reset_index()


def fast_cross_section(
    df: pd.DataFrame,
    date_col: str,
    value_col: str,
    dates: list[str] | None = None,
) -> pd.DataFrame:
    if not POLARS_AVAILABLE or df.empty:
        if dates:
            return df[df[date_col].isin(dates)]
        return df

    try:
        pl_df = pl.from_pandas(df)
        if dates:
            pl_df = pl_df.filter(pl.col(date_col).is_in(dates))
        result = pl_df.sort(date_col)
        return result.to_pandas()
    except Exception as e:
        logger.debug("Polars cross section failed, falling back to pandas: %s", e)
        if dates:
            return df[df[date_col].isin(dates)]
        return df
