# -*- coding: utf-8 -*-
"""song_regression_rerank

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1lC_kZrYkki4EIUftLyxC7o1oq-jF57Y8

[카카오 아레나 포럼
_CF](https://arena.kakao.com/forum/topics/227)
"""

from google.colab import drive
drive.mount('/content/drive')

!pip install fire

import numpy as np
import pandas as pd

import scipy.sparse as spr
import pickle
from scipy.sparse import hstack
from collections import Counter

from scipy.io import mmwrite
from scipy.io import mmread

#song_meta = pd.read_json("drive/My Drive/KAKAO/song_meta.json")

cd /content/drive/My Drive/Kakao arena

"""# Pre_processing

orig/train, val 불러서  

1. train만 over_song5로 전처리
2. train sparse matrix 만들기(target)  

3. train 데이터에 meta 정보 추가
4. feature engineering
5. LGBM 학습 모델 원래 song_id로 저장(sid2id dict에 람다 사용)
6. tag model는 생성된 tag_id로 학습된 모델 저장하고 원래 tag랑 mapping dict 유지해놓을것
"""

## real train, val 불러오자
train = pd.read_json('/content/drive/My Drive/Kakao arena/data/meta/train.json')
test = pd.read_json('/content/drive/My Drive/Kakao arena/data/meta/val.json')

song_meta = pd.read_json('/content/drive/My Drive/Kakao arena/data/meta/song_meta.json', typ = 'frame',encoding='utf-8')
plylst_meta = pd.DataFrame(train[['id','tags','plylst_title']])

"""## 1. train만 over_song5로 전처리"""

plylst_song_map = train[['id', 'songs']]

# unnest songs
plylst_song_map_unnest = np.dstack(
    (
        np.repeat(plylst_song_map.id.values, list(map(len, plylst_song_map.songs))), 
        np.concatenate(plylst_song_map.songs.values)
    )
)

# unnested 데이터프레임 생성 : plylst_song_map
plylst_song_map = pd.DataFrame(data = plylst_song_map_unnest[0], columns = plylst_song_map.columns)
plylst_song_map['id'] = plylst_song_map['id'].astype(str)
plylst_song_map['songs'] = plylst_song_map['songs'].astype(str)

# unnest 객체 제거
del plylst_song_map_unnest

value = plylst_song_map['songs'].value_counts() > 5

df = plylst_song_map['songs'].value_counts().rename_axis('unique_values').to_frame('counts')
df = df.reset_index() ; df.head(3)
over_5 = df[df['counts']>=5]

requred_song = over_5['unique_values'].tolist()
requred_song = set(list(map(int, requred_song)))

df = pd.DataFrame(columns=['over5_songs'])
train = pd.concat([train,df])

for i in range(train.shape[0]):     
    result = set(train['songs'][i]) & requred_song
    train['over5_songs'][i] = list(result)

del train['songs']
train.rename(columns = {'over5_songs' : 'songs'}, inplace = True)
train.head()

"""## 2. train sparse matrix 만들기(target)"""

train['istrain'] = 1
test['istrain'] = 0

n_train = len(train)
n_test = len(test)

# train + test
plylst = pd.concat([train,test], ignore_index=True)
plylst["nid"] = range(n_train+n_test)

# id <-> nid

plylst_id_nid = dict(zip(plylst["id"],plylst["nid"]))   # nid랑 id 값 각 값이 어떤 값을 나타내는지 저장 dict으로 저장
plylst_nid_id = dict(zip(plylst["nid"],plylst["id"]))   # 앞이 key값, 뒤가 value (id_nid는 id가 key 값, nid가 value 값)

plylst_tag = plylst['tags']
tag_counter = Counter([tg for tgs in plylst_tag for tg in tgs])  # 각 tag가 몇개 있는지 저장 dict을 () 값으로 묶은 Counter 객체
tag_dict = {x: tag_counter[x] for x in tag_counter}             # 그래서 dict으로 풀어줘야함

tag_id_tid = dict()
tag_tid_id = dict()
for i, t in enumerate(tag_dict):            # tag에는 tid 값 부여하기~
    tag_id_tid[t] = i
    tag_tid_id[i] = t

n_tags = len(tag_dict)                  # n_tags에 tag값 부여하기

plylst_song = plylst['songs']           # 각 plylst의 song들
song_counter = Counter([sg for sgs in plylst_song for sg in sgs])
song_dict = {x: song_counter[x] for x in song_counter}

song_id_sid = dict()
song_sid_id = dict()
for i, t in enumerate(song_dict):       # song에는 sid 값 부여하기~
    song_id_sid[t] = i
    song_sid_id[i] = t

n_songs = len(song_dict)

# plylst의 songs와 tags를 새로운 id로 변환하여 데이터프레임에 추가
plylst['songs_id'] = plylst['songs'].map(lambda x: [song_id_sid.get(s) for s in x if song_id_sid.get(s) != None]) # get ; key로 value 얻기
plylst['tags_id'] = plylst['tags'].map(lambda x: [tag_id_tid.get(t) for t in x if tag_id_tid.get(t) != None])

## 원래 id 찾아가는 dict
sid2id = {v: k for k, v in song_id_sid.items()}

## tid2tag 저장
file=open("sid2id","wb") 
pickle.dump(sid2id,file) 
file.close()

plylst_use = plylst
plylst_use.loc[:,'num_songs'] = plylst_use['songs_id'].map(len)
plylst_use.loc[:,'num_tags'] = plylst_use['tags_id'].map(len)
plylst_use = plylst_use.set_index('nid')

plylst_train = plylst_use.iloc[:n_train,:]
plylst_test = plylst_use.iloc[n_train:,:]

import math
from tqdm import tqdm

def rating(number):
  return [-math.log(x+1,2) +8.66 for x in range(number)]

# csr_matrix > (행,열)로 데이터 위치 표시
row = np.repeat(range(n_train),plylst_train['num_songs'])
col = [song for songs in plylst_train['songs_id'] for song in songs]
dat_series = plylst_train['num_songs'].map(rating)
dat = [y for x in dat_series for y in x]
train_songs_A = spr.csr_matrix((dat, (row, col)), shape=(n_train, n_songs))

train_songs_A  # song은 20만 곡으로 줄었음

len(train_songs_A.T[0:145000].data)

len(train_songs_A.T[145000:].data) ## 145000번 곡 까지만 타겟으로 사용 뒤에는 비어있음

song_target = train_songs_A.T[0:145000].T

"""## 3. raw train에 meta 정보 추가
raw train 기준으로 meta 정보 담고, 이후에 over_5로 곡을 줄여준다
"""

## real train, val 불러오자
train = pd.read_json('/content/drive/My Drive/Kakao arena/data/meta/train.json')
test = pd.read_json('/content/drive/My Drive/Kakao arena/data/meta/val.json')
song_meta = pd.read_json('/content/drive/My Drive/Kakao arena/data/meta/song_meta.json', typ = 'frame',encoding='utf-8')
plylst_meta = pd.DataFrame(train[['id','tags','plylst_title']])

plylst_song_map = train[['id', 'songs']]

plylst_song_map_unnest = np.dstack(
    (
        np.repeat(plylst_song_map.id.values, list(map(len, plylst_song_map.songs))), 
        np.concatenate(plylst_song_map.songs.values)
    )
)

plylst_song_map = pd.DataFrame(data = plylst_song_map_unnest[0], columns = plylst_song_map.columns)
plylst_song_map['id'] = plylst_song_map['id'].astype(str)
plylst_song_map['songs'] = plylst_song_map['songs'].astype(str)

del plylst_song_map_unnest

plylst_song_map = plylst_song_map.astype(float)
plylst_song_map = plylst_song_map.astype(int)

song_meta.head(3)

plylst_song_map = pd.merge(plylst_song_map,song_meta,how='left',left_on='songs',right_index=True)
plylst_song_map = plylst_song_map.drop('id_y',axis=1)
plylst_song_map.rename(columns={'id_x':'id'},inplace=True)
plylst_song_map.head()

plylst_meta = pd.DataFrame(train[['id','tags','plylst_title']])
plylst_meta.head(3)

for column in plylst_song_map.columns[1:]:
  plylst_sum = pd.DataFrame(plylst_song_map.groupby('id')[column].apply(list))
  plylst_sum = plylst_sum.reset_index()

  plylst_sum['id'] = plylst_sum['id'].astype(str).astype(int)
  plylst_meta = pd.merge(plylst_meta,plylst_sum,left_on='id',right_on='id',how='inner')

plylst_meta.head(3)

list_columns = ['song_gn_dtl_gnr_basket','artist_id_basket','song_gn_gnr_basket','artist_name_basket']

for column in list_columns:
  plylst_meta[f'{column}_flatten'] = plylst_meta[column].map(lambda x : sum(x,[])) # 이중리스트 단일 리스트로. (list_columns의 column들이 이중리스트인 것들)
  plylst_meta[f'{column}_unique'] = plylst_meta[f'{column}_flatten'].map(lambda x : list(set(x))) # 리스트 > 집합 > 리스트로 unique한 값 남김
  plylst_meta[f'{column}_count'] = plylst_meta[f'{column}_unique'].map(lambda x : len(x)) # unique한 것 개수 세기

meta = plylst_meta[['id','tags','plylst_title','songs','issue_date','song_gn_gnr_basket_flatten','artist_id_basket_flatten','artist_id_basket_count','song_gn_gnr_basket_count']]

meta.head(3)

"""## over_5"""

plylst_song_map = train[['id', 'songs']]

# unnest songs
plylst_song_map_unnest = np.dstack(
    (
        np.repeat(plylst_song_map.id.values, list(map(len, plylst_song_map.songs))), 
        np.concatenate(plylst_song_map.songs.values)
    )
)

# unnested 데이터프레임 생성 : plylst_song_map
plylst_song_map = pd.DataFrame(data = plylst_song_map_unnest[0], columns = plylst_song_map.columns)
plylst_song_map['id'] = plylst_song_map['id'].astype(str)
plylst_song_map['songs'] = plylst_song_map['songs'].astype(str)

# unnest 객체 제거
del plylst_song_map_unnest

value = plylst_song_map['songs'].value_counts() > 5

df = plylst_song_map['songs'].value_counts().rename_axis('unique_values').to_frame('counts')
df = df.reset_index() ; df
over_5 = df[df['counts']>=5]

requred_song = over_5['unique_values'].tolist()
requred_song = set(list(map(int, requred_song)))

df = pd.DataFrame(columns=['over5_songs'])
meta = pd.concat([meta,df])

for i in range(meta.shape[0]):     
    result = set(meta['songs'][i]) & requred_song
    meta['over5_songs'][i] = list(result)

del meta['songs']
meta.rename(columns = {'over5_songs' : 'songs'}, inplace = True)
meta['updt_date'] = train['updt_date']

meta

"""# Util function"""

import io
import os
import json
import distutils.dir_util
from collections import Counter

import numpy as np

def write_json(data, fname):
    def _conv(o):
        if isinstance(o, np.int64) or isinstance(o, np.int32):
            return int(o)
        raise TypeError

    parent = os.path.dirname(fname)
    distutils.dir_util.mkpath("./arena_data/" + parent)
    with io.open("./arena_data/" + fname, "w", encoding="utf8") as f:
        json_str = json.dumps(data, ensure_ascii=False, default=_conv)
        f.write(json_str)


def load_json(fname):
    with open(fname, encoding='utf8') as f:
        json_obj = json.load(f)

    return json_obj


def debug_json(r):
    print(json.dumps(r, ensure_ascii=False, indent=4))

class CustomEvaluator:
    def _idcg(self, l):
        return sum((1.0 / np.log(i + 2) for i in range(l)))

    def __init__(self):
        self._idcgs = [self._idcg(i) for i in range(101)]

    def _ndcg(self, gt, rec):
        dcg = 0.0
        for i, r in enumerate(rec):
            if r in gt:
                dcg += 1.0 / np.log(i + 2)

        return dcg / self._idcgs[len(gt)] # self._idcgs[len(gt)] = 0

    def _eval(self, gt_fname, rec_fname):
        gt_playlists = load_json(gt_fname)
        gt_dict = {g["id"]: g for g in gt_playlists} # 정답 {플레이리스트 아이디 : 플레이리스트 정보 쭉}
        rec_playlists = load_json(rec_fname)

        gt_ids = set([g["id"] for g in gt_playlists]) # 정답 플레이리스트 아이디
        rec_ids = set([r["id"] for r in rec_playlists]) # 답안 플레이리스트 아이디 


        music_ndcg = 0.0
        tag_ndcg = 0.0

        for rec in rec_playlists:
            gt = gt_dict[rec["id"]]
            music_ndcg += self._ndcg(gt["songs"], rec["songs"][:100])
            tag_ndcg += self._ndcg(gt["tags"], rec["tags"][:10])

        music_ndcg = music_ndcg / len(rec_playlists)
        tag_ndcg = tag_ndcg / len(rec_playlists)
        score = music_ndcg * 0.85 + tag_ndcg * 0.15

        return music_ndcg, tag_ndcg, score

    def evaluate(self, gt_fname, rec_fname): # gt > 정답, rec > 제출 답안
        try:
            music_ndcg, tag_ndcg, score = self._eval(gt_fname, rec_fname)
            print(f"Music nDCG: {music_ndcg:.6}")
            print(f"Tag nDCG: {tag_ndcg:.6}")
            print(f"Score: {score:.6}")
        except Exception as e:
            print(e)

"""# Featrue engineering
input이 spare 하지 않다 -> 구지 FM을 쓸 필요가 없다.  
XGBoost나 다른 regression 고려
"""

train = meta

"""### Season 
봄, 여름, 가을, 겨울
"""

train['updt_date'] = pd.to_datetime(train['updt_date'], format='%Y-%m-%d %H:%M:%S', errors='raise')

train['date'] = train['updt_date'].dt.date         # YYYY-MM-DD(문자)
train['year']     = train['updt_date'].dt.year         # 연(4자리숫자)
train['month']      = train['updt_date'].dt.month        # 월(숫자)
train['season'] = train['updt_date'].dt.quarter

train['season'][train['month'].isin([1,2,12])] = 4  # 겨울
train['season'][train['month'].isin([3,4,5])] = 1   # 봄
train['season'][train['month'].isin([6,7,8])] = 2  # 여름
train['season'][train['month'].isin([9,10,11])] = 3  # 가을

train.head(3)

"""### Year_section"""

df = pd.DataFrame(columns=['year_section'])
train = pd.concat([train,df])

train['year_section'][train['year'].isin([2005,2006,2007,2008,2009,2010,2011,2012])] = 1
train['year_section'][train['year'].isin([2013,2014])] = 2
train['year_section'][train['year'].isin([2015,2016])] = 3
train['year_section'][train['year'].isin([2017,2018])] = 4
train['year_section'][train['year'].isin([2019,2020])] = 5

del train['date']
del train['updt_date']

train.head(3)

"""기존 month, year은 공선성 문제가 있을테니 제거?? -> ㅇㅇ"""

X = train.drop('issue_date',axis= 1)
X.head(3)
""" plylst_title => 타이틀 임배딩 벡터?
    song_gn_gnr_basket_flatten => 장르 cnt-hot-encoding
    artist_id_basket_flatten => 아티스트 임배딩 벡터?
    tags => 태그 임배딩?

    일단 빼고 implement
"""

X.head(3)

"""### 장르 임배딩"""

from collections import Counter
genre_gn_all = pd.read_json('/content/drive/My Drive/Kakao arena/data/meta/genre_gn_all.json', typ = 'series')
genre_gn_all = pd.DataFrame(genre_gn_all, columns = ['gnr_name']).reset_index().rename(columns = {'index' : 'gnr_code'})
gnr_code = genre_gn_all[genre_gn_all['gnr_code'].str[-2:] == '00']
code2idx = {code:i for i, code in gnr_code['gnr_code'].reset_index(drop=True).items()}
code2idx['GN9000'] = 30

def genre_cnt(x):
    counter = Counter(x)
    out = np.zeros(31)
    for gnr, cnt in counter.items():
        out[code2idx[gnr]] = cnt
    return out/len(x)

X_gn = pd.concat([X, pd.DataFrame(list(X['song_gn_gnr_basket_flatten'].apply(genre_cnt)))],axis=1)

X_gn = X_gn.add_prefix('gn_')

X_gn.rename(columns = {'gn_id':'id','gn_plylst_title':'plylst_title','gn_song_gn_gnr_basket_flatten':'song_gn_gnr_basket_flatten','gn_artist_id_basket_flatten':'artist_id_basket_flatten',
                      'gn_artist_id_basket_count':'artist_id_basket_count','gn_song_gn_gnr_basket_count':'song_gn_gnr_basket_count','gn_tags':'tags','gn_year':'year','gn_month':'month',
                      'gn_season':'season','gn_year_section':'year_section'},inplace=True)

X_gn.head(3)

## 저장
X_gn.to_json('tem.json', orient='table')

"""### tag 임배딩"""

from gensim.models import Word2Vec
tags = [p for p in X['tags'] if len(p) != 1]

m = Word2Vec(tags, size=32)

tag_vector = m.wv

tags = tag_vector.vocab.keys()
tag_vector_lst = [tag_vector[v] for v in tags]

## 저장 
from gensim.models import KeyedVectors
tag_vector.save_word2vec_format('tag2v')

def tag_embed(x):
    tem = []
    for tag in x:
        try:
            tem.append(tag_vector.get_vector(tag))
        except KeyError as e:
            pass
    if tem == []:
        return np.zeros(32)
    else:
        return np.mean(tem,axis=0)

X_total = pd.concat([X_gn ,pd.DataFrame(list(X['tags'].apply(tag_embed)))],axis=1)

X_total.rename(columns = {0:'tag_0',1:'tag_1',2:'tag_2',3:'tag_3',4:'tag_4',5:'tag_5',6:'tag_6',7:'tag_7',8:'tag_8',9:'tag_9',10:'tag_10',11:'tag_11',12:'tag_12',
                          13:'tag_13',14:'tag_14',15:'tag_15',16:'tag_16',17:'tag_17',18:'tag_18',19:'tag_19',20:'tag_20',21:'tag_21',22:'tag_22',23:'tag_23',24:'tag_24',25:'tag_25',26:'tag_26',27:'tag_27',28:'tag_28',29:'tag_29',30:'tag_30',31:'tag_31'},inplace=True)

X_total.rename(columns = {0:'tag_0',1:'tag_1',2:'tag_2',3:'tag_3',4:'tag_4',5:'tag_5',6:'tag_6',7:'tag_7',8:'tag_8',9:'tag_9',10:'tag_10',11:'tag_11',12:'tag_12',
                          13:'tag_13',14:'tag_14',15:'tag_15'},inplace=True)

X_total.head(3)

## X_total 저장
X_total.to_json('X_total.json', orient='table')

## GN9000 - 장르분류X col 제거
## X_train : id 등등을 제거한 train set
X_total = X_total.drop('gn_30',axis=1)
X_total = X_total.drop('song_gn_gnr_basket_flatten',axis=1)
X_total = X_total.drop('artist_id_basket_flatten',axis=1)
X_total = X_total.drop('year', axis=1)
X_total = X_total.drop('month', axis=1)
X_total = X_total.drop('tags', axis=1)
X_train = X_total.drop('plylst_title',axis=1)
X_train = X_train.drop('id',axis=1)
X_train = X_train.drop('gn_songs',axis=1)

X_train.head(3)

## 저장 
X_train.to_json('X_train.json', orient='table')
"""
artist_cnt, gn_cnt, season, year_section -> 11차원
장르 cnt-hot-encoding : 비율 -> 30차원
태그 w2v -> 32차원

총 input features 57차원
"""

X_train = pd.read_json('X_train.json', orient='table')

## season, year_section one-hot encoding

df_season = pd.get_dummies(X_train['season']).add_prefix('season') 
df_year = pd.get_dummies(X_train['year_section']).add_prefix('year_section') 
X_train = pd.concat([X_train,df_season,df_year],axis=1)

X_train.rename(columns={'season1.0':'season_1','season2.0':'season_2','season3.0':'season_3','season4.0':'season_4','year_section1.0':'year_1','year_section2.0':'year_2','year_section3.0':'year_3','year_section4.0':'year_4','year_section5.0':'year_5'})

del X_train['season']
del X_train['year_section']

## cnt 변수 정규화
X_train['artist_id_basket_count'] = (X_train['artist_id_basket_count'] - X_train['artist_id_basket_count'].mean())/X_train['artist_id_basket_count'].std()
X_train['song_gn_gnr_basket_count'] = (X_train['song_gn_gnr_basket_count'] -X_train['song_gn_gnr_basket_count'].mean())/X_train['song_gn_gnr_basket_count'].std()

X_train

## 저장 
X_train.to_json('song_train.json', orient='table')
"""
artist_cnt, gn_cnt, season, year_section -> 11차원
장르 cnt-hot-encoding : 비율 -> 30차원
태그 w2v -> 32차원

총 input features 73차원
"""

X_train = X_train.astype(float)
X_spr = spr.csr_matrix(X_train)
X_spr

song_target

full = hstack((X_spr,song_target))
full = full.tocsc() ; full

mmwrite('song_full.mtx', full)