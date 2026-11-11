#!/bin/bash
set -euo pipefail
test -f /var/lib/kosmos/portal-login.json
export DEBIAN_FRONTEND=noninteractive
curl -fL --retry 2 https://prdownloads.sourceforge.net/webadmin/newkey-webmin_2.670_all.deb -o /var/tmp/kosmos-webmin.deb
printf '%s  %s\n' '9fdacf6b219a186ec5d7dbbbe0f46e9802cbd7050d91605bd0dfc48e150e47dc' '/var/tmp/kosmos-webmin.deb' | sha256sum -c -
apt-get install -y --no-install-recommends /var/tmp/kosmos-webmin.deb
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/webmin/miniserv.conf');lines=p.read_text().splitlines();replacements={'bind':'127.0.0.1','ssl':'0','allow':'127.0.0.1'}
lines=[x for x in lines if x.split('=',1)[0] not in replacements]
p.write_text('\n'.join(lines+[k+'='+v for k,v in replacements.items()])+'\n')
PY
systemctl restart webmin

python3 - <<'PY'
import json,secrets
from pathlib import Path
p=Path('/var/lib/kosmos/portal-login.json');data=json.loads(p.read_text())
if 'webmin_password' not in data:
 data.update(webmin_username='kosmos-admin',webmin_password=secrets.token_urlsafe(24),webmin_url=data['url']+'/webmin/')
 p.write_text(json.dumps(data));p.chmod(0o600)
host=data['url'].split('://',1)[1]
changes={'config':{'referers':host,'webprefix':'/webmin','webprefixnoredir':'1'},'miniserv.conf':{'bind':'127.0.0.1','allow':'127.0.0.1','ssl':'0','redirect_ssl':'1','redirect_host':host,'redirect_prefix':'/webmin','cookiepath':'/webmin'}}
for name,values in changes.items():
 p=Path('/etc/webmin')/name;lines=p.read_text().splitlines();lines=[line for line in lines if line.split('=',1)[0] not in values];p.write_text('\n'.join(lines+[k+'='+v for k,v in values.items()])+'\n')
PY
cat > /var/lib/kosmos/create-webmin-user.pl <<'PERL'
use lib '/usr/share/webmin';
use JSON::PP;
$ENV{'WEBMIN_CONFIG'}='/etc/webmin';
$ENV{'WEBMIN_VAR'}='/var/webmin';
require 'web-lib.pl';
&init_config();
&foreign_require('acl','acl-lib.pl');
open(my $f,'<','/var/lib/kosmos/portal-login.json') or die 'private configuration missing';
my $json;{local $/;$json=<$f>;}my $config=decode_json($json);close($f);
my @existing=&acl::list_users();
if (!grep { $_->{'name'} eq $config->{'webmin_username'} } @existing) {
 my @modules=grep {-d '/usr/share/webmin/'.$_} ('init','proc','syslog','webminlog','backup-config','system-status');
 my $user={name=>$config->{'webmin_username'},pass=>&acl::encrypt_password($config->{'webmin_password'},'$6$'.substr($config->{'webmin_password'},0,16).'$'),modules=>\@modules};
 &acl::create_user($user);
}
print "Dedicated Webmin-only manager account configured\n";
PERL
chmod 600 /var/lib/kosmos/create-webmin-user.pl
install -m 600 /var/lib/kosmos/create-webmin-user.pl /usr/share/webmin/acl/kosmos-create-user.pl
cd /usr/share/webmin/acl
perl /usr/share/webmin/acl/kosmos-create-user.pl
rm /usr/share/webmin/acl/kosmos-create-user.pl
systemctl restart webmin
sleep 2
curl -s --max-time 5 -o /dev/null -w 'Loopback Webmin HTTP %{http_code}\n' http://127.0.0.1:10000/
ss -lntp | grep ':10000'
