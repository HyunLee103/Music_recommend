import os
import json
import copy
import random
import io
import distutils.dir_util
import fire  # simple command line interface
import numpy as np

def write_json(data, fname):
    def _conv(o):
        if isinstance(o, (np.int64, np.int32)):
            return int(o)
        raise TypeError

    parent = os.path.dirname(fname)
    distutils.dir_util.mkpath("./arena_data/" + parent)
    with io.open("./arena_data/" + fname, "w", encoding="utf-8") as f:
        json_str = json.dumps(data, ensure_ascii=False, default=_conv)
        f.write(json_str)
        
def load_json(fname):
    with open(fname, encoding="utf-8") as f:
        json_obj = json.load(f)

    return json_obj


class ArenaSplitter:
    def _split_data(self, playlists):
        tot = len(playlists)
        train = playlists[:int(tot*0.80)]  # 80%
        val = playlists[int(tot*0.80):]    # 20%
        print("Count")
        print("train:", len(train))
        print("val:", len(val))

        return train, val

    def _mask(self, playlists, mask_cols, del_cols):
        # mask_cols -> partially used
        # del_cols -> deleted columns. if songs or tags
        q_pl = copy.deepcopy(playlists)  # quenstion list -> test data
        a_pl = copy.deepcopy(playlists)  # answer list -> label

        for i in range(len(playlists)):
            for del_col in del_cols:
                q_pl[i][del_col] = []  # make column empty
                if del_col == 'songs':
                    a_pl[i][del_col] = a_pl[i][del_col][:100]  # answer -> top 100
                elif del_col == 'tags':
                    a_pl[i][del_col] = a_pl[i][del_col][:10]  # top 10
                # same with our task!

            for col in mask_cols:
                mask_len = len(playlists[i][col])
                mask = np.full(mask_len, False)
                mask[:mask_len//2] = True  # masking ratio 0.5
                np.random.shuffle(mask)

                q_pl[i][col] = list(np.array(q_pl[i][col])[mask])
                a_pl[i][col] = list(np.array(a_pl[i][col])[np.invert(mask)])

        return q_pl, a_pl

    def _mask_data(self, playlists):
        playlists = copy.deepcopy(playlists)
        tot = len(playlists)
        
        # make various test data case
        song_only = playlists[:int(tot * 0.3)]
        song_and_tags = playlists[int(tot * 0.3):int(tot * 0.8)]
        tags_only = playlists[int(tot * 0.8):int(tot * 0.95)]
        title_only = playlists[int(tot * 0.95):]

        print(f"Total: {len(playlists)}, "
              f"Song only: {len(song_only)}, "
              f"Song & Tags: {len(song_and_tags)}, "
              f"Tags only: {len(tags_only)}, "
              f"Title only: {len(title_only)}")

        # self._mask(playlist, mask, delete)
        song_q, song_a = self._mask(song_only, ['songs'], ['tags'])
        songtag_q, songtag_a = self._mask(song_and_tags, ['songs', 'tags'], [])
        tag_q, tag_a = self._mask(tags_only, ['tags'], ['songs'])
        title_q, title_a = self._mask(title_only, [], ['songs', 'tags'])

        # into unified list
        q = song_q + songtag_q + tag_q + title_q
        a = song_a + songtag_a + tag_a + title_a

        # shuffle
        shuffle_indices = np.arange(len(q))
        np.random.shuffle(shuffle_indices)

        q = list(np.array(q)[shuffle_indices])
        a = list(np.array(a)[shuffle_indices])

        return q, a

    def run(self, fname):
        random.seed(777)

        print("Reading data...\n")
        playlists = load_json(fname)  # load train.json
        random.shuffle(playlists)  # shuffle data
        print(f"Total playlists: {len(playlists)}")

        print("Splitting data...")
        train, val = self._split_data(playlists)  # 8:2 split. nothing special

        # make new directory & save split data
        print("Original train...")
        write_json(train, "orig/train.json")
        print("Original val...")
        write_json(val, "orig/val.json")

        print("Masked val...")
        val_q, val_a = self._mask_data(val)
        write_json(val_q, "questions/val.json")
        write_json(val_a, "answers/val.json")


if __name__ == "__main__":
    fire.Fire(ArenaSplitter)
