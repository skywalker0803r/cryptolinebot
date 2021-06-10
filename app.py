# -*- coding: utf-8 -*-
from flask import Flask, request, abort
import requests
import json
from linebot import (LineBotApi, WebhookHandler)
import time
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import *
import pandas as pd
import configparser
import datetime
import requests
from bs4 import BeautifulSoup
import json
import numpy as np
import finlab_crypto
from finlab_crypto import Strategy
from finlab_crypto.overfitting import CSCV
import matplotlib.pyplot as plt
import copy

# 回測優化
def Optimization(pair,freq):
  ohlcv = finlab_crypto.crawler.get_all_binance(pair,freq)
  @Strategy(sma1=20, sma2=60)
  def sma_strategy(ohlcv):
    close = ohlcv.close
    sma1 = close.rolling(sma_strategy.sma1).mean()
    sma2 = close.rolling(sma_strategy.sma2).mean()
    entries = (sma1 > sma2) & (sma1.shift() < sma2.shift())
    exits = (sma1 < sma2) & (sma1.shift() > sma2.shift())
    figures = {'overlaps': {'sma1': sma1,'sma1': sma2}}
    return entries, exits, figures
  variables = {
      'sma1': np.arange(10, 100, 5), 
      'sma2': np.arange(10, 100, 5),
      }
  portfolio = sma_strategy.backtest(ohlcv, variables=variables, freq=freq ,plot=False)
  cscv = CSCV(n_bins=10, objective=lambda r: r.mean())
  cscv.add_daily_returns(portfolio.daily_returns())
  cscv_result = cscv.estimate_overfitting(plot=False)
  pbo_test = str(cscv_result['pbo_test']*100)[:4]
  temp = portfolio.total_profit()[portfolio.total_profit()==portfolio.total_profit().max()].to_frame().reset_index()
  n1 = temp['sma1'].values[0]
  n2 = temp['sma2'].values[0]
  return n1,n2,pair,ohlcv,pbo_test

# 取得訊號
def GetSignal(n1,n2,pair,ohlcv):
  table = pd.DataFrame()
  table['close'] = ohlcv.close
  table['n1'] = ohlcv.close.rolling(n1).mean()
  table['n2'] = ohlcv.close.rolling(n2).mean()
  table['buy'] = ((table['n1'] > table['n2'])&(table['n1'].shift() < table['n2'].shift())).astype(int)
  table['sell'] = ((table['n1'] < table['n2'])&(table['n1'].shift() > table['n2'].shift())).astype(int)
  table = table.replace(0,np.nan)
  table = table.dropna(subset=['buy','sell'],how='all').tail(1)
  return table

# 建立Flask app實例
app = Flask(__name__,static_url_path = "/images" , static_folder = "./images/" )

# Line的一些使用者金鑰設定
config = configparser.ConfigParser()
config.read("config.ini")
line_bot_api = LineBotApi(config['line_bot']['Channel_Access_Token'])
handler = WebhookHandler(config['line_bot']['Channel_Secret'])

# 伺服器的一些設定
secretFileContentJson=json.load(open("./line_secret_key",'r'))
server_url=secretFileContentJson.get("server_url")

# 定義路由器
@app.route("/", methods=['POST'])
def index():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 定義接收到文字訊息要如何處理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_input = event.message.text
    if '@' in user_input:
        cmd = user_input.split('@')[1].split(' ')[0]
        pair = user_input.split('@')[1].split(' ')[1]
        freq = '4h'
        if cmd == 'getsignal':
            n1,n2,pair,ohlcv,pbo_test = Optimization(pair,freq)
            table = GetSignal(n1,n2,pair,ohlcv)
            last_signal_time = str(table.index[0])
            if table['buy'].values[0] == 1.0:
                last_signal = 'buy'
            if table['sell'].values[0] == 1.0:
                last_signal = 'sell'
            context = f'標得物:{pair}\n最近一次信號時間:{last_signal_time}\n類型:{last_signal}\n均線1:{n1}均線2:{n2}\n過擬合機率:{pbo_test}%'
            line_bot_api.reply_message(event.reply_token,TextSendMessage(text=context))
        else:
            context = '=========使用說明===========\n請輸入格式例如\n @getsignal BTCUSDT \n來取得BTCUSDT最近多空訊號' 
            line_bot_api.reply_message(event.reply_token,TextSendMessage(text=context))
    else:
        context = '=========使用說明===========\n請輸入格式例如\n @getsignal BTCUSDT \n來取得BTCUSDT最近多空訊號' 
        line_bot_api.reply_message(event.reply_token,TextSendMessage(text=context))

# 主程序
if __name__ == "__main__":
    app.run(host='127.0.0.1', port=2336, debug=False)