# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import pandas as pd
import numpy as np

from reco_utils.common.constants import (
    DEFAULT_USER_COL,
    DEFAULT_ITEM_COL,
    DEFAULT_RATING_COL
)


def user_item_pairs(
    user_df,
    item_df,
    user_col=DEFAULT_USER_COL,
    item_col=DEFAULT_ITEM_COL,
    user_item_filter_df=None,
    shuffle=True,
):
    """Get all pairs of users and items data.

    Args:
        user_df (pd.DataFrame): User data containing unique user ids and maybe their features.
        item_df (pd.DataFrame): Item data containing unique item ids and maybe their features.
        user_col (str): User id column name.
        item_col (str): Item id column name.
        user_item_filter_df (pd.DataFrame): User-item pairs to be used as a filter.
        shuffle (bool): If True, shuffles the result.

    Returns:
        pd.DataFrame: All pairs of user-item from user_df and item_df, excepting the pairs in user_item_filter_df
    """

    # Get all user-item pairs
    user_df["key"] = 1
    item_df["key"] = 1
    users_items = user_df.merge(item_df, on="key")

    user_df.drop("key", axis=1, inplace=True)
    item_df.drop("key", axis=1, inplace=True)
    users_items.drop("key", axis=1, inplace=True)

    # Filter
    if user_item_filter_df is not None:
        users_items = filter_by(users_items, user_item_filter_df, [user_col, item_col])

    if shuffle:
        users_items = users_items.sample(frac=1).reset_index(drop=True)

    return users_items


def filter_by(df, filter_by_df, filter_by_cols):
    """From the input DataFrame (df), remove the records whose target column (filter_by_cols) values are
    exist in the filter-by DataFrame (filter_by_df)

    Args:
        df (pd.DataFrame): Source dataframe.
        filter_by_df (pd.DataFrame): Filter dataframe.
        filter_by_cols (iterable of str): Filter columns.

    Returns:
        pd.DataFrame: Dataframe filtered by filter_by_df on filter_by_cols
    """

    return df.loc[
        ~df.set_index(filter_by_cols).index.isin(
            filter_by_df.set_index(filter_by_cols).index
        )
    ]


def libffm_converter(df, col_rating=DEFAULT_RATING_COL, filepath=None):
    """Converts an input Dataframe (df) to another Dataframe (df) in libffm format. A text file of the converted
    Dataframe is optionally generated.

    Note:
        The input dataframe is expected to represent the feature data in the following schema
        |field-1|field-2|...|field-n|rating|
        |feature-1-1|feature-2-1|...|feature-n-1|1|
        |feature-1-2|feature-2-2|...|feature-n-2|0|
        ...
        |feature-1-i|feature-2-j|...|feature-n-k|0|
        Where
        1. each "field-*" is the column name of the dataframe (column of lable/rating is excluded), and
        2. "feature-*-*" can be either a string or a numerical value, representing the categorical variable or
        actual numerical variable of the feature value in the field, respectively.
        3. If there are ordinal variables represented in int types, users should make sure these columns
        are properly converted to string type.

        The above data will be converted to the libffm format by following the convention as explained in
        https://www.csie.ntu.edu.tw/~r01922136/slides/ffm.pdf

        i.e., <field_index>:<field_feature_index>:1 or <field_index>:<field_index>:<field_feature_value>, depending on
        the data type of the features in the original dataframe.

    Examples:
        >>> import pandas as pd
        >>> df_feature = pd.DataFrame({
                'rating': [1, 0, 0, 1, 1],
                'field1': ['xxx1', 'xxx2', 'xxx4', 'xxx4', 'xxx4'],
                'field2': [3, 4, 5, 6, 7],
                'field3': [1.0, 2.0, 3.0, 4.0, 5.0],
                'field4': ['1', '2', '3', '4', '5']
            })

        >>> df_out = libffm_converter(df_feature, col_rating='rating')
        >>> df_out
            rating field1 field2   field3 field4
        0       1  1:1:1  2:2:3  3:3:1.0  4:4:1
        1       0  1:2:1  2:2:4  3:3:2.0  4:5:1
        2       0  1:3:1  2:2:5  3:3:3.0  4:6:1
        3       1  1:3:1  2:2:6  3:3:4.0  4:7:1
        4       1  1:3:1  2:2:7  3:3:5.0  4:8:1

    Args:
        df (pd.DataFrame): input Pandas dataframe.
        col_rating (str): rating of the data.
        filepath (str): path to save the converted data.

    Return:
        pd.DataFrame: data in libffm format.
    """
    df_new = df.copy()

    # Check column types.
    types = df_new.dtypes
    if not all([x == object or np.issubdtype(x, np.integer) or x == np.float for x in types]):
        raise TypeError("Input columns should be only object and/or numeric types.")

    field_names = list(df_new.drop(col_rating, axis=1).columns)

    # Encode field-feature.
    idx = 1
    field_feature_dict = {}
    for field in field_names:
        if df_new[field].dtype == object:
            for feature in df_new[field].values:
                # Check whether (field, feature) tuple exists in the dict or not.
                # If not, put them into the key-values of the dict and count the index.
                if (field, feature) not in field_feature_dict:
                    field_feature_dict[(field, feature)] = idx
                    idx += 1

    def _convert(field, feature, field_index, field_feature_index_dict):
        if isinstance(feature, str):
            field_feature_index = field_feature_index_dict[(field, feature)]
            feature = 1
        else:
            field_feature_index = field_index

        return "{}:{}:{}".format(field_index, field_feature_index, feature)

    for col_index, col in enumerate(field_names):
        df_new[col] = df_new[col].apply(lambda x: _convert(col, x, col_index+1, field_feature_dict))

    # Move rating column to the first.
    field_names.insert(0, col_rating)
    df_new = df_new[field_names]

    if filepath is not None:
        np.savetxt(filepath, df_new.values, delimiter=' ', fmt='%s')

    return df_new


def negative_feedback_sampler(
    df, 
    col_user=DEFAULT_USER_COL,
    col_item=DEFAULT_ITEM_COL,
    number_neg_per_pos=1,
    seed=42
):
    """Utility function to sample negative feedback from user-item interaction dataset.

    This negative sampling function will take the user-item interaction data to create 
    binarized feedback, i.e., 1 and 0 indicate positive and negative feedback, 
    respectively. 
    
    Examples:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
            'userID': [1, 2, 3],
            'itemID': [1, 2, 3],
            'rating': [5, 5, 5]
        })
        >>> df_neg_sampled = negative_sampler_from_user_item_tuple(
            df, col_user='userID', col_item='itemID', number_neg_per_pos=1
        )
        >>> df_neg_sampled
        userID  itemID  feedback
        1   1   1
        1   2   0
        2   2   1
        2   1   0
        3   3   1
        3   1   0

    Args:
        df (pandas.DataFrame): input data that contains user-item tuples.
        col_user (str): user id column name.
        col_item (str): item id column name.
        number_neg_per_pos (int): number of negative feedback sampled for each positive feedback on the user-item interactive data. 
        seed (int): seed for the random state of the sampling function.

    Returns:
        pandas.DataFrame: data with negative feedback 
    """
    columns = df.columns
    if col_user not in columns:
        raise ValueError("Column {} is not in the dataframe".format(col_user))

    if col_item not in columns:
        raise ValueError("Column {} is not in the dataframe".format(col_item))

    # Get all of the users and items.
    users, items = df[col_user].unique(), df[col_item].unique()

    # Create a dataframe for all user-item pairs
    user_item_tuples = [(row[col_user], row[col_item]) for _, row in df.iterrows()]

    # Generate feedback for both positive and negative
    user_item_feedback = []
    for user in users:
        for item in items:
            feedback = 1 if (user, item) in user_item_tuples else 0
            user_item_feedback.append((user, item, feedback))

    df_all = pd.DataFrame(user_item_feedback, columns=[col_user, col_item, 'rating'])

    # Take all positive feedback
    df_pos = df_all[df_all['rating'] == 1]

    # Sample # negative feedback for each user
    # If the total negative feedback for a user is less than the sampling size, all of the 
    # negative feedback will be generated.
    df_neg = df_all[df_all['rating'] == 0]
    df_neg_sample = (
        df_neg
        .groupby(col_user)
        .apply(lambda x: x.sample(
            n=min(number_neg_per_pos, len(x)),
            random_state=seed, 
            replace=False))
        .reset_index(drop=True)
    )

    # Concatenate the positive and negative feedback dataframes
    df_sampled = (
        pd.concat([df_pos, df_neg_sample], ignore_index=True)
        .sort_values(by=[col_user, col_item])
    )

    return df_sampled
