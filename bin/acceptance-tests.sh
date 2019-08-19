#!/bin/bash
EXIT=0
BASE_URL=${1:-https://basket.mozilla.org}
URLS=(
    "/"
    "/healthz/"
    "/readiness/"
)
ADMIN_URL="/admin/"
NEWSLETTER_URLS=(
    "/news/"
    "/news/newsletters/"
)

function check_http_code {
    echo -n "Checking URL ${1} "
    curl -k -s -o /dev/null -I -w "%{http_code}" $1 | grep ${2:-200} > /dev/null
    if [ $? -eq 0 ];
    then
        echo "OK"
    else
        echo "Failed"
        EXIT=1
    fi
}

function check_zero_content_length {
    echo -n "Checking zero content length of URL ${1} "
    test=$(curl -L -s ${1} | wc -c);
    if [[ $test -eq 0 ]];
    then
        echo "OK"
    else
        echo "Failed"
        EXIT=1
    fi
}

function check_empty_json {
    echo -n "Checking empty json for URL ${1} "
    test=$(curl -L -s ${1});
    if [ $test = '{}' ];
    then
        echo "OK"
    else
        echo "Failed"
        EXIT=1
    fi
}

for url in ${URLS[*]}
do
    check_http_code ${BASE_URL}${url}
done

# Check a page that throws 404. Not ideal but will surface 500s
check_http_code ${BASE_URL}/foo 404

if [[ "$BASE_URL" =~ "admin" ]]; then
    check_http_code ${BASE_URL}/admin/ 302
    check_http_code ${BASE_URL}/admin/login/
    for url in ${NEWSLETTER_URLS[*]}; do
        check_http_code ${BASE_URL}${url} 404
    done
elif [[ "$BASE_URL" =~ "dev" ]]; then
    # admin & newsletters are both enabled in dev
    check_http_code ${BASE_URL}/admin/ 302
    check_http_code ${BASE_URL}/admin/login/
    for url in ${NEWSLETTER_URLS[*]}; do
        check_http_code ${BASE_URL}${url}
    done
else
    check_http_code ${BASE_URL}/admin/ 301
    check_http_code ${BASE_URL}/admin/login/ 404
    for url in ${NEWSLETTER_URLS[*]}; do
        check_http_code ${BASE_URL}${url}
    done
fi

exit ${EXIT}
