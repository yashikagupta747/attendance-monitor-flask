import sqlite3

conn = sqlite3.connect('attendance.db')
c = conn.cursor()

print("USERS TABLE:")
for row in c.execute("SELECT * FROM users"):
    print(row)

print("\nATTENDANCE TABLE:")
for row in c.execute("SELECT * FROM attendance"):
    print(row)

conn.close()
