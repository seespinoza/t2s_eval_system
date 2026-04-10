import pytest
from src.utils.sql_parser import count_joins, extract_table_names


class TestCountJoins:
    def test_no_joins(self):
        assert count_joins("SELECT id FROM orders") == 0

    def test_empty_string(self):
        assert count_joins("") == 0

    def test_none_equivalent_empty(self):
        assert count_joins(None) == 0

    def test_simple_join(self):
        sql = "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id"
        assert count_joins(sql) == 1

    def test_inner_join(self):
        sql = "SELECT * FROM orders INNER JOIN customers ON orders.customer_id = customers.id"
        assert count_joins(sql) == 1

    def test_left_join(self):
        sql = "SELECT * FROM orders LEFT JOIN customers ON orders.customer_id = customers.id"
        assert count_joins(sql) == 1

    def test_left_outer_join(self):
        sql = "SELECT * FROM orders LEFT OUTER JOIN customers ON orders.customer_id = customers.id"
        assert count_joins(sql) == 1

    def test_right_join(self):
        sql = "SELECT * FROM a RIGHT JOIN b ON a.id = b.id"
        assert count_joins(sql) == 1

    def test_right_outer_join(self):
        sql = "SELECT * FROM a RIGHT OUTER JOIN b ON a.id = b.id"
        assert count_joins(sql) == 1

    def test_full_join(self):
        sql = "SELECT * FROM a FULL JOIN b ON a.id = b.id"
        assert count_joins(sql) == 1

    def test_full_outer_join(self):
        sql = "SELECT * FROM a FULL OUTER JOIN b ON a.id = b.id"
        assert count_joins(sql) == 1

    def test_cross_join(self):
        sql = "SELECT * FROM a CROSS JOIN b"
        assert count_joins(sql) == 1

    def test_multiple_joins(self):
        sql = """
            SELECT * FROM orders
            JOIN customers ON orders.customer_id = customers.id
            LEFT JOIN products ON orders.product_id = products.id
            INNER JOIN warehouses ON products.warehouse_id = warehouses.id
        """
        assert count_joins(sql) == 3

    def test_case_insensitive(self):
        sql = "select * from orders join customers on orders.customer_id = customers.id"
        assert count_joins(sql) == 1

    def test_comment_stripped_before_counting(self):
        sql = """
            SELECT * FROM orders
            -- JOIN fake_table ON orders.id = fake_table.id
            JOIN customers ON orders.customer_id = customers.id
        """
        assert count_joins(sql) == 1

    def test_join_in_comment_only(self):
        sql = "SELECT * FROM orders -- JOIN customers ON orders.id = customers.id"
        assert count_joins(sql) == 0

    def test_cte_with_join(self):
        sql = """
            WITH cte AS (
                SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id
            )
            SELECT * FROM cte
        """
        assert count_joins(sql) == 1

    def test_subquery_with_join(self):
        sql = """
            SELECT * FROM (
                SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id
            ) sub
            JOIN products ON sub.product_id = products.id
        """
        assert count_joins(sql) == 2


class TestExtractTableNames:
    def test_empty_string(self):
        assert extract_table_names("") == []

    def test_none_equivalent_empty(self):
        assert extract_table_names(None) == []

    def test_single_table(self):
        assert extract_table_names("SELECT * FROM orders") == ["orders"]

    def test_table_with_join(self):
        result = extract_table_names(
            "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id"
        )
        assert sorted(result) == ["customers", "orders"]

    def test_multiple_joins(self):
        sql = """
            SELECT * FROM orders
            JOIN customers ON orders.customer_id = customers.id
            LEFT JOIN products ON orders.product_id = products.id
        """
        result = extract_table_names(sql)
        assert sorted(result) == ["customers", "orders", "products"]

    def test_case_insensitive_lowercased(self):
        result = extract_table_names("SELECT * FROM Orders JOIN Customers ON Orders.id = Customers.id")
        assert sorted(result) == ["customers", "orders"]

    def test_deduplicated(self):
        sql = "SELECT * FROM orders JOIN orders ON orders.a = orders.b"
        assert extract_table_names(sql) == ["orders"]

    def test_backtick_quoted_table(self):
        result = extract_table_names("SELECT * FROM `my_table` JOIN `other_table` ON `my_table`.id = `other_table`.id")
        assert sorted(result) == ["my_table", "other_table"]

    def test_comment_stripped(self):
        sql = """
            SELECT * FROM orders
            -- FROM fake_table
            JOIN customers ON orders.customer_id = customers.id
        """
        result = extract_table_names(sql)
        assert "fake_table" not in result
        assert sorted(result) == ["customers", "orders"]

    def test_sorted_output(self):
        sql = "SELECT * FROM zebra JOIN apple ON zebra.id = apple.id"
        result = extract_table_names(sql)
        assert result == sorted(result)
