#!/bin/sh
V_DATABASE=${DATABASE:-"tpcds"}
V_DBMS=${DBMS:-"db2"}
V_DATA_DIR=${DATA_DIR:-"/data"}

if [ ! -f ${V_DBMS}_setup.sh ]
then
echo "Cannot find setup file for DBMS: ${V_DBMS}_setup.sh"
exit 1
fi

. ${V_DBMS}_setup.sh
connect_to $V_DATABASE

cd temp_build
if [ -f FAILED ]
then
exit
fi

if [ -z "$1" ]
then
	activate_constraints tpcds_ri.sql
else
	run_query $V_DATABASE tpcds_ri.sql
	activate_constraints tpcds_ri.sql
fi
