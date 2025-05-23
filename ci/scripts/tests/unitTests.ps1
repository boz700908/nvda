$outDir = (Resolve-Path .\testOutput\unit\)
$unitTestsXml = "$outDir\unitTests.xml"
.\rununittests.bat --output-file "$unitTestsXml" -v
if ($LastExitCode -ne 0) {
	$message = "FAIL: Unit tests. See test results for more information."
	Write-Output "testFailExitCode=$LastExitCode" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
} else {
	$message = "PASS: Unit tests."
}
$message >> $env:GITHUB_STEP_SUMMARY
exit $LastExitCode
