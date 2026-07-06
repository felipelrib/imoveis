$env:PGPASSWORD = 'password'
$env:PGUSER = 'user'
$env:PGHOST = 'localhost'
$env:PGPORT = '5432'
$env:PGDATABASE = 'realestate'

alembic upgrade head
