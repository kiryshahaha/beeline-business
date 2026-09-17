"""Add offices and link to brigades

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-17 17:20:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create offices table
    op.create_table(
        'offices',
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=False),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.CheckConstraint("name = btrim(name) AND name <> ''", name='name_not_blank'),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name='fk_offices_location_id', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uq_offices_name', 'offices', [sa.text('lower(name)')], unique=True)
    
    # 2. Add office_id to brigades (nullable first)
    op.add_column('brigades', sa.Column('office_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_brigades_office_id', 'brigades', 'offices', ['office_id'], ['id'], ondelete='RESTRICT')
    
    # 3. Create dummy office for existing brigades and update them
    op.execute("""
        DO $$
        DECLARE
            dummy_city_id integer;
            dummy_street_id integer;
            dummy_district_id integer;
            dummy_building_id integer;
            dummy_location_id integer;
            dummy_office_id integer;
        BEGIN
            IF EXISTS (SELECT 1 FROM brigades) THEN
                -- Find or create a city
                SELECT id INTO dummy_city_id FROM cities LIMIT 1;
                IF dummy_city_id IS NULL THEN
                    INSERT INTO cities (name) VALUES ('Дефолтный Город') RETURNING id INTO dummy_city_id;
                END IF;
                
                -- Find or create a street
                SELECT id INTO dummy_street_id FROM streets LIMIT 1;
                IF dummy_street_id IS NULL THEN
                    INSERT INTO streets (name, city_id) VALUES ('Дефолтная Улица', dummy_city_id) RETURNING id INTO dummy_street_id;
                END IF;
                
                -- Find or create a district
                SELECT id INTO dummy_district_id FROM districts LIMIT 1;
                IF dummy_district_id IS NULL THEN
                    INSERT INTO districts (name, city_id) VALUES ('Дефолтный Район', dummy_city_id) RETURNING id INTO dummy_district_id;
                END IF;

                -- Find or create a building
                SELECT id INTO dummy_building_id FROM buildings LIMIT 1;
                IF dummy_building_id IS NULL THEN
                    INSERT INTO buildings (city_id, street_id, district_id, number) 
                    VALUES (dummy_city_id, dummy_street_id, dummy_district_id, '1') RETURNING id INTO dummy_building_id;
                END IF;
                
                -- Find or create a location
                SELECT id INTO dummy_location_id FROM locations LIMIT 1;
                IF dummy_location_id IS NULL THEN
                    INSERT INTO locations (building_id) VALUES (dummy_building_id) RETURNING id INTO dummy_location_id;
                END IF;
                
                INSERT INTO offices (name, location_id) VALUES ('Дефолтный Офис', dummy_location_id) RETURNING id INTO dummy_office_id;
                UPDATE brigades SET office_id = dummy_office_id WHERE office_id IS NULL;
            END IF;
        END $$;
    """)
    
    # 4. Alter column to not null
    op.alter_column('brigades', 'office_id', existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    op.drop_constraint('fk_brigades_office_id', 'brigades', type_='foreignkey')
    op.drop_column('brigades', 'office_id')
    op.drop_index('uq_offices_name', table_name='offices')
    op.drop_table('offices')
