# strategies/ai_strategy.py

import pandas as pd
import xgboost as xgb
from joblib import dump, load
import os

class AIStrategy:
    def __init__(self, model_path='models/xgb_model.joblib'):
        self.model_path = model_path
        if os.path.exists(self.model_path):
            self.model = load(self.model_path)
        else:
            self.model = xgb.XGBClassifier(objective='multi:softmax', num_class=3, use_label_encoder=False, eval_metric='mlogloss')

    def _calculate_features(self, df):
        """
        Calculates technical indicators and features for the model.
        """
        # EMA
        df['EMA_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI_14'] = 100 - (100 / (1 + rs))

        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        df['MACD_12_26_9'] = macd - signal
        
        # Bollinger Bands
        df['BBM_20_2.0'] = df['close'].rolling(window=20).mean()
        df['BBU_20_2.0'] = df['BBM_20_2.0'] + 2 * df['close'].rolling(window=20).std()
        df['BBL_20_2.0'] = df['BBM_20_2.0'] - 2 * df['close'].rolling(window=20).std()

        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df['ATRr_14'] = true_range.rolling(window=14).mean()

        # Stochastic Oscillator
        low_14 = df['low'].rolling(window=14).min()
        high_14 = df['high'].rolling(window=14).max()
        df['STOCHk_14_3_3'] = 100 * ((df['close'] - low_14) / (high_14 - low_14))
        df['STOCHd_14_3_3'] = df['STOCHk_14_3_3'].rolling(window=3).mean()

        df.dropna(inplace=True)
        return df

    def train(self, historical_data):
        """
        Trains the model on historical data.
        """
        df = pd.DataFrame(historical_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = self._calculate_features(df)
        
        # Create target variable and map for XGBoost
        # Sell: -1 -> 0
        # Hold:  0 -> 1
        # Buy:   1 -> 2
        df['target'] = 1 # Default to Hold
        df.loc[df['close'].shift(-5) > df['close'], 'target'] = 2 # Buy
        df.loc[df['close'].shift(-5) < df['close'], 'target'] = 0 # Sell
        
        features = [
            'EMA_20', 'EMA_50', 'RSI_14', 'MACD_12_26_9', 'BBL_20_2.0', 
            'BBM_20_2.0', 'BBU_20_2.0', 'ATRr_14', 'STOCHk_14_3_3', 'STOCHd_14_3_3', 'volume'
        ]
        X = df[features]
        y = df['target']
        
        # Ensure all feature columns are numeric before training
        for col in X.columns:
            X[col] = pd.to_numeric(X[col], errors='coerce')
        X.fillna(0, inplace=True) # Replace any remaining NaNs with 0
        
        self.model.fit(X, y)
        
        # Ensure the 'models' directory exists before saving
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        dump(self.model, self.model_path)
        print(f"Model trained and saved to {self.model_path}")

    def predict(self, current_data):
        """
        Makes a prediction based on the latest market data.
        Can accept a single row or a full dataframe.
        """
        df = pd.DataFrame(current_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = self._calculate_features(df)
        
        if not df.empty:
            features = [
                'EMA_20', 'EMA_50', 'RSI_14', 'MACD_12_26_9', 'BBL_20_2.0', 
                'BBM_20_2.0', 'BBU_20_2.0', 'ATRr_14', 'STOCHk_14_3_3', 'STOCHd_14_3_3', 'volume'
            ]
            # Ensure all feature columns exist, fill with 0 if not (can happen for single-row prediction)
            for col in features:
                if col not in df.columns:
                    df[col] = 0
            X = df[features]
            predictions = self.model.predict(X)
            # Remap predictions back to -1, 0, 1
            # 0 -> -1 (Sell)
            # 1 ->  0 (Hold)
            # 2 ->  1 (Buy)
            return [p - 1 for p in predictions]
        return []
