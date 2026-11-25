import json
from deploy.preflight import check


def configured(tmp_path):
    return {'ADMIN_TOKEN':'private-fixture-'+'x'*40,'ADMIN_ACTOR':'operator',
            'ADMIN_PUBLIC_ORIGIN':'https://shengcai.school.edu.cn','ADMIN_COOKIE_SECURE':'1',
            'ADMIN_DATA_DIR':str(tmp_path),'STUDENT_BASE_URL':'http://127.0.0.1:8000',
            'PROPOSITION_BASE_URL':'http://127.0.0.1:8001'}


def test_configuration_ready_without_database_initialization(tmp_path):
    env=configured(tmp_path)
    report=check(env)
    assert report['ok'] and not list(tmp_path.iterdir())
    assert env['ADMIN_TOKEN'] not in json.dumps(report)


def test_insecure_and_placeholder_configuration_is_rejected(tmp_path):
    for key,value in [('PORTAL_DEMO','1'),('ADMIN_COOKIE_SECURE','0'),('ADMIN_PUBLIC_ORIGIN','http://unsafe.example'),
                      ('ADMIN_PUBLIC_ORIGIN','https://management.example.org'),('ADMIN_DATA_DIR','relative'),
                      ('STUDENT_BASE_URL','http://10.0.0.2:8000'),('PROPOSITION_BASE_URL','https://user:secret@host')]:
        env=configured(tmp_path);env[key]=value
        assert not check(env)['ok'], key
