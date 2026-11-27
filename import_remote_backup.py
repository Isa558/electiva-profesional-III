import argparse
import getpass
import re

import MySQLdb


def load_statements(path):
    sql = open(path, "r", encoding="utf-8-sig").read()
    return [statement.strip() for statement in re.split(r";\s*(?:\r\n|\n|$)", sql) if statement.strip()]


def main():
    parser = argparse.ArgumentParser(description="Importa test_backup.sql en MariaDB/MySQL remoto.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--database", default="test")
    parser.add_argument("--sql-file", default=r"C:\Users\Acer\Downloads\test_backup_extracted\test_backup.sql")
    parser.add_argument("--ssl-ca")
    args = parser.parse_args()

    password = getpass.getpass("Contraseña remota: ")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.database):
        raise ValueError("El nombre de base de datos no es válido.")
    options = {}
    if args.ssl_ca:
        options["ssl"] = {"ca": args.ssl_ca, "check_hostname": True}

    connection = MySQLdb.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        database=None,
        **options,
    )
    password = ""

    try:
        cursor = connection.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{args.database}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        cursor.execute(f"USE `{args.database}`")

        for statement in load_statements(args.sql_file):
            cursor.execute(statement)
        connection.commit()

        counts = {}
        for name, table in (
            ("questions", "evaluaciones_question"),
            ("quizzes", "evaluaciones_quiz"),
            ("attempts", "evaluaciones_attempt"),
            ("answers", "evaluaciones_attemptanswer"),
        ):
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts[name] = cursor.fetchone()[0]
        print(counts)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
