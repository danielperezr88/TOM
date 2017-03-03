#!/usr/bin/env python2
# -*- coding: UTF-8 -*-

from pattern.es import parse as parse_es
from pattern.en import parse as parse_en
import pandas as pd
from StringIO import StringIO
import argparse


def df_pos(text, language='es'):
    parsers = dict(es=parse_es,en=parse_en)
    text = unicode(text, encoding='latin-1').encode('latin-1')
    return pd.read_table(
        StringIO("\n".join(parsers[language](text).encode('latin-1').split())),
        sep='/', header=None, quoting=3, encoding='latin-1')

def pattern_pos_filter_text(text, types, language):
    df = df_pos(text, language)
    df = df[[0,1]][~df[1].isin(types)]
    return df.values


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('text', type=str, help="Text to process")
    parser.add_argument('--types', nargs='+', help="List of types to filter")
    parser.add_argument('--language', type=str, default='es', help="Language for POS tagging")
    args = parser.parse_args()

    res = pattern_pos_filter_text(
        args.text,
        args.types,
        args.language
    ).tolist()

    for row in res:
        print_row = '\t'.join(row)
        print print_row.encode('latin-1')
