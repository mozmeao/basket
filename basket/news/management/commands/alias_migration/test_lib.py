from collections import namedtuple
from unittest.mock import Mock

from .lib import (
    build_alias_operations_from_dataframe,
    build_alias_operations_from_dataframe_row,
    create_batched_chunks,
)

Row = namedtuple("Pandas", ["email_id", "basket_token", "fxa_id"])
RowWithoutFxa = namedtuple("Pandas", ["email_id", "basket_token"])


class TestBuildAliasOperationsFromDataframeRow:
    def test_row_with_all_fields(self):
        """Test row with email_id, basket_token, and fxa_id"""
        row = Row(email_id="ext_123", basket_token="basket_abc", fxa_id="fxa_456")

        result = build_alias_operations_from_dataframe_row(row)

        expected = [
            {
                "external_id": "ext_123",
                "alias_label": "basket_token",
                "alias_name": "basket_abc",
            },
            {
                "external_id": "ext_123",
                "alias_label": "fxa_id",
                "alias_name": "fxa_456",
            },
        ]

        assert result == expected

    def test_row_without_fxa_id_attribute(self):
        """Test row that doesn't have fxa_id attribute at all"""
        row = RowWithoutFxa(email_id="ext_123", basket_token="basket_abc")

        result = build_alias_operations_from_dataframe_row(row)

        expected = [
            {
                "external_id": "ext_123",
                "alias_label": "basket_token",
                "alias_name": "basket_abc",
            }
        ]

        assert result == expected

    def test_row_with_empty_fxa_id(self):
        """Test row with empty fxa_id"""
        row = Row(email_id="ext_123", basket_token="basket_abc", fxa_id="")

        result = build_alias_operations_from_dataframe_row(row)

        expected = [
            {
                "external_id": "ext_123",
                "alias_label": "basket_token",
                "alias_name": "basket_abc",
            }
        ]

        assert result == expected


class TestBuildAliasOperationsFromDataframe:
    def test_empty_dataframe(self):
        """Test with empty dataframe"""
        mock_dataframe = Mock()
        mock_dataframe.itertuples.return_value = []

        result = build_alias_operations_from_dataframe(mock_dataframe)

        assert result == []

    def test_single_row_dataframe(self):
        """Test dataframe with single row"""
        row = Row(email_id="ext_123", basket_token="basket_abc", fxa_id="fxa_456")

        mock_dataframe = Mock()
        mock_dataframe.itertuples.return_value = [row]

        result = build_alias_operations_from_dataframe(mock_dataframe)

        expected = [
            {
                "external_id": "ext_123",
                "alias_label": "basket_token",
                "alias_name": "basket_abc",
            },
            {
                "external_id": "ext_123",
                "alias_label": "fxa_id",
                "alias_name": "fxa_456",
            },
        ]

        assert result == expected

    def test_multiple_rows_dataframe(self):
        """Test dataframe with multiple rows"""
        row1 = Row(email_id="ext_123", basket_token="basket_abc", fxa_id="fxa_456")
        row2 = RowWithoutFxa(email_id="ext_789", basket_token="basket_def")
        row3 = Row(
            email_id="ext_999",
            basket_token="basket_xyz",
            fxa_id="",  # Empty fxa_id
        )

        mock_dataframe = Mock()
        mock_dataframe.itertuples.return_value = [row1, row2, row3]

        result = build_alias_operations_from_dataframe(mock_dataframe)

        expected = [
            # From row1
            {
                "external_id": "ext_123",
                "alias_label": "basket_token",
                "alias_name": "basket_abc",
            },
            {
                "external_id": "ext_123",
                "alias_label": "fxa_id",
                "alias_name": "fxa_456",
            },
            # From row2
            {
                "external_id": "ext_789",
                "alias_label": "basket_token",
                "alias_name": "basket_def",
            },
            # From row3
            {
                "external_id": "ext_999",
                "alias_label": "basket_token",
                "alias_name": "basket_xyz",
            },
        ]

        assert result == expected
        assert len(result) == 4


class TestCreateBatchedChunks:
    def test_evenly_divisible_operations(self):
        """Test when operations divide evenly into chunks and batches."""
        operations = list(range(1, 13))  # 12 operations
        batch_size = 2
        chunk_size = 3

        result = create_batched_chunks(operations, batch_size, chunk_size)
        expected = [
            [[1, 2, 3], [4, 5, 6]],
            [[7, 8, 9], [10, 11, 12]],
        ]

        assert result == expected

    def test_uneven_chunks(self):
        """Test when operations don't divide evenly into chunks."""
        operations = list(range(1, 11))  # 10 operations
        batch_size = 2
        chunk_size = 3

        result = create_batched_chunks(operations, batch_size, chunk_size)
        expected = [
            [[1, 2, 3], [4, 5, 6]],
            [[7, 8, 9], [10]],
        ]

        assert result == expected

    def test_uneven_batches(self):
        """Test when chunks don't divide evenly into batches."""
        operations = list(range(1, 16))  # 15 operations
        batch_size = 2
        chunk_size = 3

        result = create_batched_chunks(operations, batch_size, chunk_size)
        expected = [
            [[1, 2, 3], [4, 5, 6]],
            [[7, 8, 9], [10, 11, 12]],
            [[13, 14, 15]],
        ]

        assert result == expected
