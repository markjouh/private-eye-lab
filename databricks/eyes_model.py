"""Packaging wrapper that puts the phone model files in the Unity Catalog model registry.

The model itself runs on the phone (llama.cpp, GGUF); Databricks does not serve it. Registering it
gives each fine-tune a version, a link to the MLflow run and training table that produced it, and
one governed place to download the exact file that is on the device. predict() lists the files.
"""
import os

import mlflow
import pandas as pd
from mlflow.pyfunc import PythonModel


class EyesPhoneModel(PythonModel):
    def load_context(self, context):
        self.files = dict(context.artifacts)

    def predict(self, context, model_input, params=None):
        rows = []
        for name, path in self.files.items():
            size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs) if os.path.isdir(path) else os.path.getsize(path)
            rows.append({"file": name, "path": path, "megabytes": round(size / 1e6, 1)})
        return pd.DataFrame(rows)


mlflow.models.set_model(EyesPhoneModel())
