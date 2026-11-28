{extends file='layouts/layout-left-column.tpl'}

{block name='left_column'}
  <div id="left-column" class="col-xs-12 col-md-4 col-lg-3">
    {hook h='displayLeftColumn' mod='fishingstorefront'}
    {widget name='ps_facetedsearch' hook='displayLeftColumn'}
  </div>
{/block}
